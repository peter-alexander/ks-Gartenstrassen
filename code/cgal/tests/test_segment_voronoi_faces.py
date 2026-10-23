#!/usr/bin/env python3
"""Regression checks for finite and geometrically correct native CGAL faces."""
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile


CASES=(
	{
		"name":"A",
		"segments":((18322833,10460171,18327970,10494392),
			(18327970,10494392,18339843,10573486)),
		"point":(18329781,10494793),
		"input_segments":7,
		"segment_faces":3,
		"point_faces":5,
		"halfedges":37,
	},
	{
		"name":"B",
		"segments":((33290069,12201293,33322433,12199793),
			(33322433,12199793,33339327,12199010)),
		"point":(33328587,12188767),
		"input_segments":8,
		"segment_faces":4,
		"point_faces":6,
		"halfedges":51,
	},
)


def _run(binary,payload):
	with tempfile.TemporaryDirectory() as folder:
		output=Path(folder)/"faces.txt"
		result=subprocess.run((binary,"--faces",str(output)),
			input=payload,text=True,capture_output=True,check=False)
		if result.returncode:
			raise AssertionError(
				f"export failed ({result.returncode}): {result.stderr}")
		stats=json.loads(result.stdout)
		return output.read_text(encoding="utf-8"),stats


def _coordinates(fields,count,line_number):
	if len(fields)!=count+1:
		raise AssertionError(f"line {line_number}: malformed {fields[0]}")
	values=tuple(float(value) for value in fields[1:])
	if not all(math.isfinite(value) for value in values):
		raise AssertionError(f"line {line_number}: non-finite coordinate")
	return values


def _parse(raw):
	faces=[]
	face=None
	halfedge=None
	for line_number,line in enumerate(raw.splitlines(),1):
		fields=line.split()
		if not fields:
			continue
		kind=fields[0]
		if kind in ("F","P"):
			if face is not None:
				raise AssertionError(f"line {line_number}: nested face")
			values=_coordinates(fields,4 if kind=="F" else 2,line_number)
			face={"kind":kind,"generator":values,"halfedges":[]}
		elif kind=="H":
			if face is None or halfedge is not None:
				raise AssertionError(f"line {line_number}: misplaced H")
			values=_coordinates(fields,4,line_number)
			halfedge={"source":values[:2],"target":values[2:],"segments":0}
		elif kind in ("S","R","L"):
			_coordinates(fields,4,line_number)
			if halfedge is None:
				raise AssertionError(f"line {line_number}: detached {kind}")
			if kind!="S":
				raise AssertionError(f"line {line_number}: unbounded bounded-face edge")
			halfedge["segments"]+=1
		elif kind=="E":
			if len(fields)!=1 or halfedge is None or not halfedge["segments"]:
				raise AssertionError(f"line {line_number}: invalid E")
			face["halfedges"].append(halfedge)
			halfedge=None
		elif kind=="Z":
			if len(fields)!=1 or face is None or halfedge is not None:
				raise AssertionError(f"line {line_number}: invalid Z")
			if len(face["halfedges"])<2:
				raise AssertionError(f"line {line_number}: incomplete face")
			faces.append(face)
			face=None
		else:
			raise AssertionError(f"line {line_number}: unknown record {kind}")
	if face is not None or halfedge is not None:
		raise AssertionError("truncated face stream")
	return faces


def _segment_key(values):
	a=(round(values[0]),round(values[1]))
	b=(round(values[2]),round(values[3]))
	return tuple(sorted((a,b)))


def _point_key(values):
	return tuple(round(value) for value in values)


def _vertices(face):
	return {
		(round(point[0],6),round(point[1],6))
		for edge in face["halfedges"]
		for point in (edge["source"],edge["target"])
	}


def _segment_distance(point,segment):
	x,y=point
	x1,y1,x2,y2=segment
	dx=x2-x1
	dy=y2-y1
	fraction=max(0.0,min(1.0,
		((x-x1)*dx+(y-y1)*dy)/(dx*dx+dy*dy)))
	return math.hypot(x-(x1+fraction*dx),y-(y1+fraction*dy))


def _check_problem_case(binary,fixture,case):
	raw,stats=_run(binary,fixture.read_text(encoding="utf-8"))
	faces=_parse(raw)
	if stats["input_segments"]!=case["input_segments"]:
		raise AssertionError((case["name"],stats))
	for key,expected in (("segment_faces",case["segment_faces"]),
			("point_faces_exported",case["point_faces"]),
			("halfedges",case["halfedges"])):
		if stats[key]!=expected:
			raise AssertionError((case["name"],key,stats[key],expected))
	if "exact_vertex_fallbacks" not in stats:
		raise AssertionError("export statistics omit exact fallback count")

	wanted_segments={tuple(sorted(((s[0],s[1]),(s[2],s[3]))))
		for s in case["segments"]}
	segment_faces=[face for face in faces
		if face["kind"]=="F" and _segment_key(face["generator"])
		in wanted_segments]
	point_faces=[face for face in faces
		if face["kind"]=="P" and _point_key(face["generator"])==case["point"]]
	if len(segment_faces)!=2 or len(point_faces)!=1:
		raise AssertionError(
			f"case {case['name']}: generator provenance changed")

	common=_vertices(segment_faces[0]) & _vertices(segment_faces[1]) & \
		_vertices(point_faces[0])
	if len(common)!=1:
		raise AssertionError(
			f"case {case['name']}: expected one common Voronoi vertex, got {common}")
	vertex=next(iter(common))
	distances=[_segment_distance(vertex,segment)
		for segment in case["segments"]]
	distances.append(math.dist(vertex,case["point"]))
	if max(distances)-min(distances)>1e-3:
		raise AssertionError(
			f"case {case['name']}: non-equidistant Voronoi vertex "
			f"{vertex}, distances {distances}")
	return stats


def _check_regular_case(binary):
	payload=("0 0 20000 0\n0 10000 20000 10000\n"
		"0 20000 20000 20000\n-40000 -40000 60000 -40000\n"
		"60000 -40000 60000 60000\n60000 60000 -40000 60000\n"
		"-40000 60000 -40000 -40000\n")
	raw,stats=_run(binary,payload)
	_parse(raw)
	if stats["exact_vertex_fallbacks"]!=0:
		raise AssertionError(
			"regular geometry unexpectedly used exact construction fallback")
	if (stats["segment_faces"],stats["point_faces_exported"],
			stats["halfedges"])!=(3,6,36):
		raise AssertionError(f"regular topology changed: {stats}")


def _check_failfast(binary,fixture):
	with tempfile.TemporaryDirectory() as folder:
		output=Path(folder)/"must-not-survive.txt"
		result=subprocess.run((binary,"--faces",str(output)),
			input=fixture.read_text(encoding="utf-8"),text=True,
			capture_output=True,check=False)
		if result.returncode==0:
			raise AssertionError("non-finite test exporter unexpectedly succeeded")
		for expected in ("Face ","generator segment(","halfedge ",
				"non-finite coordinate in native halfedge"):
			if expected not in result.stderr:
				raise AssertionError(
					f"fail-fast diagnostic lacks {expected!r}: {result.stderr}")
		if output.exists():
			raise AssertionError("failed export left an incomplete face stream")


def main():
	if len(sys.argv)!=5:
		raise SystemExit(
			"usage: test_segment_voronoi_faces.py BINARY A.txt B.txt FAILFAST_BINARY")
	binary=sys.argv[1]
	results=[]
	for fixture,case in zip(map(Path,sys.argv[2:]),CASES):
		results.append(_check_problem_case(binary,fixture,case))
	_check_regular_case(binary)
	_check_failfast(sys.argv[4],Path(sys.argv[2]))
	print("CGAL finite-coordinate regressions passed:",
		", ".join(f"group {case['name']} exact fallbacks="
			f"{stats['exact_vertex_fallbacks']}"
			for case,stats in zip(CASES,results)))


if __name__=="__main__":
	main()
