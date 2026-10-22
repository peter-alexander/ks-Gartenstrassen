"""Diagnose ONE native CGAL Voronoi face from the saved face stream.

This does not call CGAL or repeat the Vienna calculation, noding, dissolve,
or SIS. The debug geometry is the exact serialized native CCB boundary,
rebuilt using the same _join_halfedge function as the live exporter.
No invalid polygon is repaired or accepted.

Example:
	python -m scripts.inspect_cgal_native_face \
		--stream ../output/cgal_native_faces_dissolved_pre_sis_wien__native_faces.txt \
		--cache ../cache/wien/linear_use_original.sqlite \
		--face 54 \
		--report ../output/cgal_face54_report.json \
		--geojson ../output/cgal_face54_edges.geojson \
		--raw ../output/cgal_face54_native.txt
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sqlite3

from pyproj import Transformer
from shapely.geometry import LineString, Polygon, mapping
from shapely.ops import transform
from shapely.validation import explain_validity
from shapely import make_valid
from shapely.wkb import loads

from scripts.cgal_native_faces import _xy, _distance, _join_halfedge


def extract_face(stream,face_number):
	"""Copy the numbered F...Z record from the native CGAL stream."""
	if face_number<1:
		raise ValueError("Face number must be >= 1")
	count=0
	active=False
	lines=[]
	with Path(stream).open(encoding="utf-8") as source:
		for lineno,line in enumerate(source,1):
			kind=line.split(maxsplit=1)[0] if line.strip() else ""
			if kind=="F":
				if active:
					raise ValueError(f"Nested F record, line {lineno}")
				count+=1
				active=count==face_number
			if active:
				lines.append(line)
				if kind=="Z":
					return lines
	if active:
		raise ValueError(f"Native CGAL face {face_number} incomplete")
	raise ValueError(f"Native CGAL face {face_number} not found; total {count}")


def source_origin(cache):
	"""Use the same metric x0/y0 as _noded_segments, without any noding."""
	minx,miny=math.inf,math.inf
	count=0
	with sqlite3.connect(f"file:{Path(cache).resolve()}?mode=ro",uri=True) as db:
		row=db.execute("SELECT value FROM metadata WHERE key='schema'").fetchone()
		if row is None or json.loads(row[0])!="linear-use-original-segments-v1":
			raise ValueError("Expected original LINEAR_USE cache")
		for (blob,) in db.execute("SELECT wkb FROM linear_use_segments"):
			geom=loads(blob)
			if geom.is_empty:
				continue
			a,b,_,_=geom.bounds
			minx=min(minx,a)
			miny=min(miny,b)
			count+=1
	if not count:
		raise ValueError("Empty original LINEAR_USE cache")
	return minx,miny


def analyze_face(lines,origin):
	"""Reassemble one native Face and explain the exact validity failure."""
	face_header=lines[0].split()
	if len(face_header)!=5 or face_header[0]!="F":
		raise ValueError("Missing native F header")
	ring=[]
	parts=[]
	active=False
	for line_number,line in enumerate(lines[1:],2):
		fields=line.split()
		if not fields:
			continue
		kind=fields[0]
		if kind=="H":
			if active or len(fields)!=5:
				raise ValueError(f"Malformed H at record {line_number}")
			values=[float(v) for v in fields[1:]]
			start=_xy(values[0],values[1],origin)
			end=_xy(values[2],values[3],origin)
			chords=[]
			active=True
		elif kind=="S":
			if not active or len(fields)!=5:
				raise ValueError(f"Malformed S at record {line_number}")
			values=[float(v) for v in fields[1:]]
			chords.append((_xy(values[0],values[1],origin),
				_xy(values[2],values[3],origin)))
		elif kind=="E":
			if not active or len(fields)!=1:
				raise ValueError(f"Malformed E at record {line_number}")
			number=len(parts)+1
			coords=_join_halfedge(chords,start,end,
				face_number=0,halfedge_number=number)
			gap_to_previous=_distance(ring[-1],coords[0]) if ring else 0.0
			if ring:
				# Match the actual native-face assembler exactly.
				if gap_to_previous>0.0005:
					raise ValueError(f"Halfedge {number} gap {gap_to_previous} m")
				coords[0]=ring[-1]
				ring.extend(coords[1:])
			else:
				ring.extend(coords)
			parts.append({"halfedge":number,"coords":coords,
				"chord_count":len(chords),
				"gap_to_previous_m":gap_to_previous,
				"length_m":LineString(coords).length})
			active=False
		elif kind=="Z":
			if active or len(fields)!=1 or line_number!=len(lines):
				raise ValueError(f"Malformed Z at record {line_number}")
		else:
			raise ValueError(f"Unexpected native CGAL record {kind}")
	if len(ring)<4:
		raise ValueError("Face has too few ring points")
	gap=_distance(ring[0],ring[-1])
	if gap<=0.0005:
		ring[-1]=ring[0]
	geom=Polygon(ring) if ring[0]==ring[-1] else None
	metrics={
		"support_site_mm":face_header[1:],
		"halfedge_count":len(parts),
		"ring_points":len(ring),
		"closed_gap_m":gap,
		"consecutive_duplicate_points":sum(a==b
			for a,b in zip(ring,ring[1:])),
		"exact_backtracks":sum(ring[i-1]==ring[i+1]
			for i in range(1,len(ring)-1)),
		"smallest_segment_m":min(_distance(a,b)
			for a,b in zip(ring,ring[1:])),
		"bbox_31256":list(LineString(ring).bounds),
		"ring_length_m":LineString(ring).length,
		"polygon_valid":geom.is_valid if geom is not None else False,
		"polygon_empty":geom.is_empty if geom is not None else None,
		"polygon_area_m2":geom.area if geom is not None else None,
		"validity_reason":explain_validity(geom)
			if geom is not None else "Ring is not closed",
		"halfedges":[{
			key:value for key,value in part.items() if key!="coords"}
			for part in parts],
		"repair_applied":False,
	}
	if geom is not None and not geom.is_valid:
		try:
			fixed=make_valid(geom)
			metrics["diagnostic_make_valid_only"]={
				"geometry_type":fixed.geom_type,
				"area_m2":fixed.area,
				"valid":fixed.is_valid,
				"polygonal_components":sum(1 for p in (
					fixed.geoms if hasattr(fixed,"geoms") else (fixed,))
					if p.geom_type in ("Polygon","MultiPolygon")),
				"not_used_for_output":True,
			}
		except Exception as exc:
			metrics["diagnostic_make_valid_error"]=str(exc)
	return metrics,ring,parts


def _write_new(path,data):
	path=Path(path)
	if path.exists() or path.is_symlink():
		raise FileExistsError(path)
	path.parent.mkdir(parents=True,exist_ok=True)
	path.write_text(data,encoding="utf-8")


def run(stream,cache,face,report,geojson,raw):
	lines=extract_face(stream,face)
	origin=source_origin(cache)
	stats,ring,parts=analyze_face(lines,origin)
	stats["face_number"]=face
	stats["origin_31256"]=list(origin)
	to_wgs=Transformer.from_crs(31256,4326,always_xy=True).transform
	features=[{"type":"Feature",
		"properties":{"kind":"ring","face_number":face,
			"validity_reason":stats["validity_reason"]},
		"geometry":mapping(transform(to_wgs,LineString(ring)))}]
	for part in parts:
		features.append({"type":"Feature",
			"properties":{"kind":"halfedge","face_number":face,
				"halfedge":part["halfedge"],"chord_count":part["chord_count"],
				"length_m":part["length_m"]},
			"geometry":mapping(transform(to_wgs,LineString(part["coords"])))})
	if raw:
		_write_new(raw,"".join(lines))
	_write_new(report,json.dumps(stats,ensure_ascii=False,indent=2)+"\n")
	_write_new(geojson,json.dumps({"type":"FeatureCollection",
		"features":features},ensure_ascii=False)+"\n")
	print(json.dumps({key:value for key,value in stats.items()
		if key!="halfedges"},ensure_ascii=False,indent=2))
	print(f"Native CGAL-Face {face}: Bericht {report}, Kanten {geojson}"
		+(f", rohe Records {raw}" if raw else ""),flush=True)
	return stats


def main():
	parser=argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--stream",type=Path,required=True)
	parser.add_argument("--cache",type=Path,required=True)
	parser.add_argument("--face",type=int,required=True)
	parser.add_argument("--report",type=Path,required=True)
	parser.add_argument("--geojson",type=Path,required=True)
	parser.add_argument("--raw",type=Path)
	args=parser.parse_args()
	run(args.stream,args.cache,args.face,args.report,args.geojson,args.raw)


if __name__=="__main__":
	main()
