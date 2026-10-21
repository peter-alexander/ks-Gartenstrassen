"""Independent sampled nearest-axis audit of existing CGAL/SIS debug output.

Read-only inputs. Sampling detects ownership errors but is not a mathematical
proof of complete cell topology; no automatic correction is performed.
"""
import argparse
import json
import math
from pathlib import Path
import sqlite3

from pyproj import Transformer
from shapely.geometry import shape, Point, box
from shapely.ops import transform
from shapely.strtree import STRtree
from shapely.wkb import loads
from shapely.validation import explain_validity


def audit(features, axes, *, tolerance_m=0.01):
	if not math.isfinite(tolerance_m) or tolerance_m<0:
		raise ValueError("Ungültige Toleranz")
	ids=sorted(axes)
	if not ids:
		raise ValueError("Keine originalen LINEAR_USE-Linien")
	lines=[]
	line_ids=[]
	own_geometries={}
	for edge_id in ids:
		source=axes[edge_id]
		parts=source if isinstance(source,(tuple,list)) else [source]
		if not parts:
			raise ValueError(f"{edge_id}: keine Originalsegmente")
		own_geometries[edge_id]=parts
		for part in parts:
			lines.append(part)
			line_ids.append(edge_id)
	tree=STRtree(lines)
	to_metric=Transformer.from_crs(4326,31256,always_xy=True).transform
	details=[]
	invalid_geometries=[]
	sampled=0
	ambiguous=0
	for index,feature in enumerate(features):
		owner=str(feature["properties"]["edge_id"])
		if owner not in axes:
			raise ValueError(f"Feature {index}: unbekannte edge_id {owner}")
		source_geometry=shape(feature["geometry"])
		geometry=transform(to_metric,source_geometry)
		if (source_geometry.is_empty or not source_geometry.is_valid
				or geometry.is_empty or not geometry.is_valid):
			invalid_geometries.append({
				"feature_index":index,"edge_id":owner,
				"reason_wgs84":explain_validity(source_geometry),
				"reason_31256":explain_validity(geometry),
				"source_valid":source_geometry.is_valid,
				"metric_valid":geometry.is_valid,
				"geometry_type":source_geometry.geom_type,
				"bounds_wgs84":list(source_geometry.bounds) if not source_geometry.is_empty else None,
				"bounds_31256":list(geometry.bounds) if not geometry.is_empty else None
			})
			continue
		parts=list(geometry.geoms) if geometry.geom_type=="MultiPolygon" else [geometry]
		for part in parts:
			if part.geom_type!="Polygon":
				raise ValueError(f"Feature {index}: keine Polygonfläche")
			minx,miny,maxx,maxy=part.bounds
			mx=(minx+maxx)/2
			my=(miny+maxy)/2
			samples=[part.representative_point()]
			for cell in (box(minx,miny,mx,my),box(mx,miny,maxx,my),
					box(minx,my,mx,maxy),box(mx,my,maxx,maxy)):
				clipped=part.intersection(cell)
				if not clipped.is_empty and clipped.area>0:
					samples.append(clipped.representative_point())
			for point in samples:
				sampled+=1
				matched=int(tree.nearest(point))
				best_distance=point.distance(lines[matched])
				own_distance=min(point.distance(g) for g in own_geometries[owner])
				# A point on an actual Voronoi boundary can have multiple
				# equally near axes. Only report material distance differences.
				difference=own_distance-best_distance
				if difference>tolerance_m:
					details.append({
						"feature_index":index,"edge_id":owner,
						"nearest_edge_id":line_ids[matched],
						"assigned_distance_m":own_distance,
						"nearest_distance_m":best_distance,
						"distance_difference_m":difference,
						"point_31256":[point.x,point.y]})
				elif line_ids[matched]!=owner and abs(difference)<=tolerance_m:
					ambiguous+=1
	return {
		"method":"five-samples-per-polygon-part-v1",
		"tolerance_m":tolerance_m,
		"features":len(features),
		"sample_points":sampled,
		"within_tolerance":sampled-len(details),
		"possible_tie_samples":ambiguous,
		"failures":len(details)+len(invalid_geometries),
		"ownership_failures":len(details),
		"invalid_geometry_count":len(invalid_geometries),
		"invalid_geometries":invalid_geometries,
		"qa_status":"failed" if details or invalid_geometries else "passed",
		"details":details,
		"interpretation":"Stichprobenprüfung, kein vollständiger Voronoi-Beweis",
	}


def run(cache,geojson,out,*,tolerance_m=0.01):
	out=Path(out)
	if out.exists() or out.is_symlink():
		raise FileExistsError(out)
	with sqlite3.connect(f"file:{Path(cache).resolve()}?mode=ro",uri=True) as db:
		schema=db.execute("SELECT value FROM metadata WHERE key='schema'").fetchone()
		if schema is None or json.loads(schema[0])!="linear-use-original-segments-v1":
			raise ValueError("Nur Original-LINEAR_USE-Cache ist zulässig")
		axes={}
		for edge_id,blob in db.execute(
				"SELECT edge_id,wkb FROM linear_use_segments"):
			axes.setdefault(str(edge_id),[]).append(loads(blob))
	with Path(geojson).open(encoding="utf-8") as source:
		collection=json.load(source)
	if collection.get("type")!="FeatureCollection":
		raise ValueError("FeatureCollection erwartet")
	report=audit(collection["features"],axes,tolerance_m=tolerance_m)
	out.parent.mkdir(parents=True,exist_ok=True)
	# Keep failed audits too: failures are findings, not an exception.
	import os
	import tempfile
	with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",
			dir=out.parent,prefix=out.name+".",suffix=".tmp",
			delete=False) as output:
		temp=Path(output.name)
		try:
			json.dump(report,output,ensure_ascii=False,indent=2,allow_nan=False)
			output.write("\n")
			output.flush()
			os.replace(temp,out)
		finally:
			temp.unlink(missing_ok=True)
	return report


def main():
	parser=argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--cache",type=Path,required=True)
	parser.add_argument("--geojson",type=Path,required=True)
	parser.add_argument("--out",type=Path,required=True)
	parser.add_argument("--tolerance-m",type=float,default=0.01)
	args=parser.parse_args()
	result=run(args.cache,args.geojson,args.out,tolerance_m=args.tolerance_m)
	print(f"Zellzuordnung: {result['sample_points']} Proben, "
		f"{result['ownership_failures']} Zuordnungsabweichungen, "
		f"{result['invalid_geometry_count']} ungültige Geometrien; Bericht: {args.out}")
	if result["failures"]:
		raise SystemExit(1)


if __name__=="__main__":
	main()
