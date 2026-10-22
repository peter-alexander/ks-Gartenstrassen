"""Investigate CGAL segment sites crossing multiple Voronoi polygon interiors.

Read only the existing __geometry_checkpoint.sqlite and AOI. Does NOT rerun
CGAL, polygonize or assign edge_ids. Deliberately does not turn overlap
into accepted ownership: tests whether the reconstructed cells really
partition the original CGAL site segments.
"""
import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile

from pyproj import Transformer
from shapely.geometry import box, mapping
from shapely.ops import transform
from shapely.strtree import STRtree
from shapely.wkb import loads

from scripts.wienwide_grid import load_aoi

SCHEMA="cgal-pre-sis-geometry-checkpoint-v1"


def _bucket(value):
	if value>=0.999:
		return "99.9-100%"
	if value>=0.95:
		return "95-99.9%"
	if value>=0.75:
		return "75-95%"
	if value>=0.5:
		return "50-75%"
	if value>=0.25:
		return "25-50%"
	return "<25%"


def analyze(faces,sites,window,*,sample_limit=15,progress=None):
	"""Measure *genuine* interior overlaps, never assign a face owner."""
	if sample_limit<0:
		raise ValueError("sample_limit must be >= 0")
	tree=STRtree(faces)
	interior_count=Counter()
	secondary_fraction=Counter()
	area_overlap=Counter()
	per_face=[set() for _ in faces]
	examples=[]
	zero=0
	for seq,(site_line,edge_id,site) in enumerate(sites,1):
		if progress and seq%20000==0:
			progress(f"CGAL-Site-Analyse: {seq:,}/{len(sites):,} Segmente")
		clipped_length=site.intersection(window).length
		if clipped_length<=1e-8:
			interior_count["outside_window"]+=1
			continue
		lengths=[]
		for index in tree.query(site,predicate="intersects"):
			i=int(index)
			if not site.relate_pattern(faces[i],"1********"):
				continue
			length=site.intersection(faces[i]).length
			if length>1e-8:
				lengths.append((i,length))
				per_face[i].add(edge_id)
		lengths.sort(key=lambda row:(-row[1],row[0]))
		n=len(lengths)
		interior_count["0" if n==0 else "1" if n==1 else "2" if n==2 else "3+"]+=1
		if n==0:
			zero+=1
		if n>=2:
			total=sum(length for _,length in lengths)
			second=lengths[1][1]/clipped_length
			secondary_fraction[_bucket(second)]+=1
			ratio=total/clipped_length
			if ratio>1.01:
				area_overlap["summed_interior_length_gt_101pct"]+=1
			elif ratio<0.99:
				area_overlap["summed_interior_length_lt_99pct"]+=1
			else:
				area_overlap["summed_interior_length_99_101pct"]+=1
			if len(examples)<sample_limit:
				examples.append({
					"site_line":site_line,"edge_id":edge_id,
					"site_length_inside_window_m":clipped_length,
					"interior_face_count":n,
					"matched_interior_length_m":total,
					"secondary_interior_fraction":second,
					"faces":[{"polygon_index":i,
						"intersection_length_m":length,
						"site_fraction":length/clipped_length}
						for i,length in lengths[:12]]})
	face_groups=Counter(
		"0" if len(ids)==0 else "1" if len(ids)==1 else "2+"
		for ids in per_face)
	return {
		"schema":"cgal-segment-site-split-analysis-v1",
		"site_count":len(sites),
		"polygon_count":len(faces),
		"interior_faces_per_site":dict(interior_count),
		"second_largest_site_piece_fraction":dict(secondary_fraction),
		"sum_of_interior_lengths_vs_clipped_site":dict(area_overlap),
		"distinct_segment_edge_ids_per_polygon":dict(face_groups),
		"site_examples":examples,
		"point_sites_processed":False,
		"edge_ids_assigned":False,
		"interpretation":"Geometric analysis only; positive interior overlap is not proof of Voronoi site ownership."}


def _load(path):
	with sqlite3.connect(f"file:{path.resolve()}?mode=ro",uri=True) as db:
		data={key:json.loads(value) for key,value in
			db.execute("SELECT key,value FROM metadata")}
		if data["identity"].get("schema")!=SCHEMA:
			raise ValueError("Not a CGAL pre-SIS geometry checkpoint")
		faces=[loads(wkb) for (wkb,) in
			db.execute("SELECT wkb FROM polygons ORDER BY id")]
		sites=[(line,edge_id,loads(wkb)) for line,edge_id,wkb in
			db.execute("SELECT site_line,edge_id,wkb FROM segment_sites ORDER BY id")]
		if len(faces)!=data["polygon_count"] or len(sites)!=data["site_count"]:
			raise ValueError("Checkpoint geometry row counts do not match")
		if not faces or not sites:
			raise ValueError("Checkpoint has no polygons or segment sites")
	return faces,sites


def _write(output,document):
	output=Path(output)
	if output.exists() or output.is_symlink():
		raise FileExistsError(output)
	output.parent.mkdir(parents=True,exist_ok=True)
	with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",
			dir=output.parent,prefix="."+output.name+".",
			suffix=".tmp",delete=False) as handle:
		temp=Path(handle.name)
		try:
			json.dump(document,handle,ensure_ascii=False,
				separators=(",",":"),allow_nan=False)
			handle.write("\n")
			handle.flush()
			os.replace(temp,output)
		finally:
			temp.unlink(missing_ok=True)


def run(checkpoint,aoi,output,examples,*,sample_limit=15):
	faces,sites=_load(Path(checkpoint))
	window=box(*load_aoi(aoi).bounds)
	print(f"CGAL: analysiere {len(sites):,} Segment-Sites "
		f"und {len(faces):,} gespeicherte Polygone",flush=True)
	data=analyze(faces,sites,window,sample_limit=sample_limit,
		progress=lambda message:print(message,flush=True))
	to_wgs=Transformer.from_crs(31256,4326,always_xy=True).transform
	site_lookup={line:(owner,geom) for line,owner,geom in sites}
	features=[]
	for entry in data["site_examples"]:
		num=entry["site_line"]
		owner,segment=site_lookup[num]
		features.append({"type":"Feature",
			"properties":{"kind":"segment_site",
				"site_line":num,"edge_id":owner,
				"interior_faces":entry["interior_face_count"],
				"secondary_fraction":entry["secondary_interior_fraction"]},
			"geometry":mapping(transform(to_wgs,segment))})
		for f in entry["faces"]:
			idx=f["polygon_index"]
			features.append({"type":"Feature",
				"properties":{"kind":"candidate_polygon",
					"polygon_index":idx,"site_line":num,
					"edge_id_of_crossing_site":owner,
					"intersection_length_m":f["intersection_length_m"],
					"site_fraction":f["site_fraction"]},
				"geometry":mapping(transform(to_wgs,faces[idx]))})
	_write(output,data)
	_write(examples,{"type":"FeatureCollection","features":features})
	print(json.dumps({k:v for k,v in data.items() if k!="site_examples"},
		ensure_ascii=False,indent=2),flush=True)
	print(f"Bericht: {output}\nBeispiele für QGIS: {examples}",flush=True)
	return data


def main():
	parser=argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--checkpoint",type=Path,required=True)
	parser.add_argument("--aoi",type=Path,required=True)
	parser.add_argument("--out",type=Path,required=True)
	parser.add_argument("--examples",type=Path,required=True)
	parser.add_argument("--sample-limit",type=int,default=15)
	args=parser.parse_args()
	run(args.checkpoint,args.aoi,args.out,args.examples,
		sample_limit=args.sample_limit)


if __name__=="__main__":
	main()
