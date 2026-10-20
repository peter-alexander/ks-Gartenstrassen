"""Validate native CGAL graph-site output against noded LINEAR_USE inputs.

CGAL graph vertices have segment sites and point sites. Endpoint point sites
can belong to multiple input segments and therefore must not be assigned an
arbitrary edge_id. This module reports ambiguity rather than hiding it.
"""
from collections import defaultdict
from pathlib import Path
import math


def _point(coords):
	values=tuple(float(v) for v in coords)
	if len(values)!=2 or not all(math.isfinite(v) for v in values):
		raise ValueError("Nicht endliche Site-Koordinate")
	return values


def inspect_sites(lines, owners, *, precision_mm=0.001):
	if precision_mm<=0:
		raise ValueError("Ungültige Präzision")
	endpoints=defaultdict(set)
	segments={}
	for (a,b),owner in owners.items():
		key=tuple(sorted((tuple(a),tuple(b))))
		segments[key]=owner
		endpoints[tuple(a)].add(owner)
		endpoints[tuple(b)].add(owner)
	counts={"point_sites":0,"segment_sites":0,"unmatched_segments":0,
		"unmatched_points":0,"ambiguous_point_sites":0,
		"examples":[]}
	def snap(point):
		rounded=tuple(round(v) for v in point)
		if any(abs(v-r)>precision_mm for v,r in zip(point,rounded)):
			return None
		return rounded
	for number,line in enumerate(lines,1):
		fields=line.strip().split()
		if not fields:
			continue
		try:
			if fields[0]=="P" and len(fields)==3:
				key=snap(_point(fields[1:]))
				counts["point_sites"]+=1
				if key not in endpoints:
					counts["unmatched_points"]+=1
				elif len(endpoints[key])>1:
					counts["ambiguous_point_sites"]+=1
			elif fields[0]=="S" and len(fields)==5:
				a=snap(_point(fields[1:3]))
				b=snap(_point(fields[3:5]))
				key=tuple(sorted((a,b))) if a is not None and b is not None else None
				counts["segment_sites"]+=1
				if key not in segments:
					counts["unmatched_segments"]+=1
			else:
				raise ValueError("Ungültiges Site-Format")
		except ValueError as exc:
			raise ValueError(f"CGAL-Sites Zeile {number}: {exc}") from exc
		if ((fields[0]=="P" and key not in endpoints)
				or (fields[0]=="S" and key not in segments)):
			if len(counts["examples"])<10:
				counts["examples"].append({"line":number,"record":line.strip()})
	return counts


def inspect_sites_file(path, owners):
	with Path(path).open(encoding="utf-8") as source:
		return inspect_sites(source, owners)
