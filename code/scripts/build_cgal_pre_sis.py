"""Original LINEAR_USE -> native CGAL segment-site cells -> dissolve, before SIS.

Point sites are deliberately omitted. Their footprint remains unassigned
and is NOT added to adjacent lines. The result is a review layer, not
a complete partition of SIS or the Vienna bounding rectangle.
"""
import argparse
from collections import defaultdict
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile

from pyproj import Transformer
from shapely import union_all
from shapely.geometry import box, mapping
from shapely.ops import transform

from scripts.build_cgal_voronoi_geojson import (
	_source_records, _frame, _payload, _read_dual_lines,
	_polygon_candidates, _connected_components, _export_wgs84_polygon)
from scripts.cgal_segment_input import SCALE, _noded_segments
from scripts.cgal_site_ownership import (
	read_sites, attribute_faces, require_sound_attribution)
from scripts.wienwide_grid import load_aoi


def _group_before_sis(polygons,labels):
	"""Only touching faces of the same edge_id are united."""
	if len(polygons)!=len(labels):
		raise ValueError("CGAL polygons and owners length mismatch")
	grouped=defaultdict(list)
	for polygon,edge_id in zip(polygons,labels):
		if edge_id is not None:
			grouped[edge_id].append(polygon)
	for edge_id in sorted(grouped):
		merged=union_all(grouped[edge_id])
		if merged.is_empty or not merged.is_valid:
			raise ValueError(f"{edge_id}: invalid segment-site union")
		for component in _connected_components(merged):
			yield edge_id,component


def build(cache,aoi_path,binary,out,*,timeout=900):
	out=Path(out)
	if out.exists() or out.is_symlink():
		raise FileExistsError(out)
	if not Path(binary).is_file():
		raise FileNotFoundError(f"CGAL binary missing: {binary}")
	if not math.isfinite(timeout) or timeout<=0:
		raise ValueError("CGAL timeout must be positive")
	aoi=load_aoi(aoi_path)
	window=box(*aoi.bounds)
	records=_source_records(cache)
	owners,origin=_noded_segments(
		[(edge_id,line) for _object_id,edge_id,line in records],
		progress=lambda message:print(message,flush=True))
	frame=_frame(aoi,origin)
	ox,oy=origin
	bounds=[round((v-(ox if i%2==0 else oy))*SCALE)
		for i,v in enumerate(window.bounds)]
	payload="".join(_payload(owners,frame))
	out.parent.mkdir(parents=True,exist_ok=True)
	with tempfile.TemporaryDirectory(prefix="cgal-native-sites-",dir=out.parent) as tmp:
		dual=Path(tmp)/"dual.txt"
		sites=Path(tmp)/"sites.txt"
		command=[str(Path(binary).resolve()),"--edges",str(dual),
			"--sites",str(sites),"--bounds",*(str(v) for v in bounds)]
		try:
			proc=subprocess.run(command,input=payload,text=True,
				capture_output=True,timeout=timeout,check=False)
		except subprocess.TimeoutExpired as exc:
			raise RuntimeError("CGAL exceeded timeout") from exc
		if proc.returncode:
			raise RuntimeError(f"CGAL native site export failed: {proc.stderr[-2000:]}")
		if not dual.is_file() or not sites.is_file():
			raise RuntimeError("CGAL missing dual or native-sites output")
		lines,dual_stats=_read_dual_lines(dual,window,origin)
		polygons,topology=_polygon_candidates(lines,window)
		segment_sites,site_stats=read_sites(sites,owners,origin)
		labels,assignment=attribute_faces(polygons,segment_sites,site_stats,window=window)
		require_sound_attribution(assignment)
		print("CGAL-Sites: "
			f"{assignment['native_segment_sites']:,} Segmentgeneratoren, "
			f"{assignment['native_point_sites_omitted']:,} Punktgeneratoren ausgelassen, "
			f"{assignment['polygons_with_segment_edge_id']:,} zugeordnete Polygone, "
			f"{assignment['polygons_without_segment_edge_id']:,} unbelegte Polygone",
			flush=True)
		to_wgs=Transformer.from_crs(31256,4326,always_xy=True).transform
		to_metric=Transformer.from_crs(4326,31256,always_xy=True).transform
		features=[]
		repairs=[]
		metric_areas=0.0
		for edge_id,connected in _group_before_sis(polygons,labels):
			converted,repair=_export_wgs84_polygon(
				connected,to_wgs,to_metric,edge_id=edge_id)
			if repair:
				repairs.append(repair)
			metric_areas+=connected.area
			features.append({"type":"Feature",
				"properties":{"edge_id":edge_id,"area_m2":connected.area,
					"method":"cgal_segment_sites_pre_sis"},
				"geometry":mapping(converted)})
		if not features:
			raise ValueError("No uniquely assigned segment Voronoi faces")
		source_area=sum(poly.area for poly,label in zip(polygons,labels)
			if label is not None)
		area_tolerance=max(0.01,source_area*1e-9)
		if abs(metric_areas-source_area)>area_tolerance:
			raise ValueError("Area balance failed during pre-SIS dissolve: "
				f"{metric_areas-source_area:.6f} m²")
		document={"type":"FeatureCollection","features":features,
			"metadata":{
				"schema":"cgal-native-segment-sites-pre-sis-v1",
				"crs":"EPSG:4326","metric_crs":"EPSG:31256",
				"source_segment_count":len(owners),
				"native_sites":assignment,
				"dual_primitives":dual_stats,
				"polygonization":topology,
				"segment_area_m2":source_area,
				"omitted_area_m2":sum(poly.area for poly,label
					in zip(polygons,labels) if label is None),
				"export_geometry_repairs":repairs,
				"sis_clipped":False,
				"point_cells_assigned":False,
				"experimental":True}}
		stage=Path(tmp)/"pre-sis.geojson"
		stage.write_text(json.dumps(document,ensure_ascii=False,
			separators=(",",":"),allow_nan=False)+"\n",encoding="utf-8")
		os.replace(stage,out)
	print(f"CGAL vor SIS: {len(features):,} zusammenhängende Gruppen; {out}",
		flush=True)
	return len(features)


def main():
	parser=argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--cache",type=Path,required=True)
	parser.add_argument("--aoi",type=Path,required=True)
	parser.add_argument("--binary",type=Path,required=True)
	parser.add_argument("--out",type=Path,required=True)
	parser.add_argument("--timeout",type=float,default=900)
	args=parser.parse_args()
	build(args.cache,args.aoi,args.binary,args.out,timeout=args.timeout)


if __name__=="__main__":
	main()
