"""Conservative generator-site / polygon association.

A genuine Voronoi cell contains its generating site (segment or point).
Polygonized dual boundaries are not labelled, so *only* uniquely covered
site interiors can provide an owner without a nearest-neighbour guess.
Ambiguous vertices and multiple sites are reported, not silently assigned.
"""
from collections import defaultdict
from pathlib import Path

from shapely.geometry import Point, LineString
from shapely.strtree import STRtree

from scripts.cgal_site_audit import _point


def _read_sites(lines, owners, origin, scale):
	endpoints=defaultdict(set)
	for (a,b),edge_id in owners.items():
		endpoints[tuple(a)].add(edge_id)
		endpoints[tuple(b)].add(edge_id)
	segment_owners={tuple(sorted((tuple(a),tuple(b)))):v
		for (a,b),v in owners.items()}
	ox,oy=origin
	result=[]
	for i,line in enumerate(lines,1):
		fields=line.split()
		if not fields:
			continue
		if fields[0]=="P" and len(fields)==3:
			p=tuple(round(v) for v in _point(fields[1:]))
			ids=endpoints.get(p,set())
			geom=Point(p[0]/scale+ox,p[1]/scale+oy)
		elif fields[0]=="S" and len(fields)==5:
			a=tuple(round(v) for v in _point(fields[1:3]))
			b=tuple(round(v) for v in _point(fields[3:5]))
			ids=set()
			owner=segment_owners.get(tuple(sorted((a,b))))
			if owner is not None:
				ids.add(owner)
			geom=LineString(((a[0]/scale+ox,a[1]/scale+oy),
				(b[0]/scale+ox,b[1]/scale+oy))).interpolate(0.5,normalized=True)
		else:
			raise ValueError(f"Site-Zeile {i}: ungültiges Format")
		if not ids:
			raise ValueError(f"Site-Zeile {i}: CGAL-Site nicht in LINEAR_USE")
		result.append((geom,frozenset(ids)))
	return result


def classify_polygon_generators(polygons, sites):
	"""Classify cells; only one uniquely owned generating site is definitive.

	Other cells are unresolved, not assigned by nearest distance.
	"""
	if not sites:
		raise ValueError("Keine CGAL-Sites")
	geoms=[s[0] for s in sites]
	tree=STRtree(geoms)
	stats={"unambiguous":0,"ambiguous":0,"missing":0}
	owners=[]
	for polygon in polygons:
		# Points on boundaries can be shared by adjacent cells. Querying
		# covers includes boundaries, so those cells stay ambiguous.
		matches=tree.query(polygon,predicate="covers")
		owners_found={sites[int(i)][1] for i in matches}
		if not owners_found:
			owners.append(None)
			stats["missing"]+=1
		elif len(owners_found)==1 and len(next(iter(owners_found)))==1:
			owners.append(next(iter(next(iter(owners_found)))))
			stats["unambiguous"]+=1
		else:
			owners.append(None)
			stats["ambiguous"]+=1
	return owners,stats


def classify_polygon_generators_file(polygons,path,owners,origin,scale):
	with Path(path).open(encoding="utf-8") as stream:
		sites=_read_sites(stream,owners,origin,scale)
	return classify_polygon_generators(polygons,sites)
