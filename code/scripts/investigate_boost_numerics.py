"""Isolated Boost experiments on the last reproducible Vienna segment set.

Tests input ordering and integer-coordinate transforms, then reports exact
topological / near-collinear relationships. Does not modify GIP source data.
"""
import argparse
import hashlib
import json
import math
import random
from collections import Counter
from pathlib import Path

from shapely.geometry import LineString
from shapely.strtree import STRtree

from scripts.benchmark_segment_voronoi import _save, _timed_construct
from scripts.build_segment_voronoi_geojson import _axes
from scripts.diagnose_boost_voronoi import _frame, _read_candidate_geojson, _resolve_resume_path
from scripts.segment_voronoi_engine import SCALE, _noded_segments
from scripts.wienwide_grid import load_aoi


def _transform(keys,frame,*,multiplier=1,dx=0,dy=0):
	"""Integer-coordinate affine transform; frame remains in matching metres."""
	if multiplier<1 or int(multiplier)!=multiplier:
		raise ValueError("Nur ganzzahlige Maßstabsfaktoren >= 1")
	def point(p):
		return (p[0]*multiplier+dx,p[1]*multiplier+dy)
	new_keys=[(point(a),point(b)) for a,b in keys]
	new_frame=[(x*multiplier+dx/SCALE,y*multiplier+dy/SCALE)
		for x,y in frame]
	if len(set(new_keys))!=len(new_keys):
		raise ValueError("Transformation erzeugt doppelte Segmente")
	return new_keys,new_frame


def _order_cases(base,site):
	"""Keep exact site geometry, changing only Boost insertion order."""
	all_sites=base+[site]
	shuffled=list(all_sites)
	random.Random(20261019).shuffle(shuffled)
	shuffled_other=list(all_sites)
	random.Random(42).shuffle(shuffled_other)
	return [
		("original",all_sites),
		("reverse_all",list(reversed(all_sites))),
		("reverse_base_suspect_last",list(reversed(base))+[site]),
		("suspect_first",[site]+base),
		("lexicographic",sorted(all_sites)),
		("lexicographic_reverse",sorted(all_sites,reverse=True)),
		("shuffle_seed_20261019",shuffled),
		("shuffle_seed_42",shuffled_other)]


def _geometry_report(keys,owners,origin,site,*,tolerance_m=0.01,max_examples=25):
	"""Fast local topology metrics on all selected segments; no Boost involved."""
	geoms=[LineString([(a[0]/SCALE,a[1]/SCALE),
		(b[0]/SCALE,b[1]/SCALE)]) for a,b in keys]
	tree=STRtree(geoms)
	incidence=Counter(p for key in keys for p in key)
	junctions=Counter(incidence.values())
	zero=0
	pairs_close=0
	examples=[]
	for i,g in enumerate(geoms):
		if g.length==0:
			zero+=1
		for index in tree.query(g.buffer(tolerance_m).envelope):
			j=int(index)
			if j<=i:
				continue
			h=geoms[j]
			d=g.distance(h)
			if d>tolerance_m:
				continue
			# Ignore ordinary connections at identical noded vertices.
			common=set(keys[i]) & set(keys[j])
			if common and d==0:
				continue
			pairs_close+=1
			if len(examples)<max_examples:
				examples.append({"edge_a":owners[keys[i]],
					"edge_b":owners[keys[j]],"distance_m":round(d,6),
					"intersects":g.intersects(h)})
	target=geoms[keys.index(site)]
	near=sorted(((target.distance(g),i) for i,g in enumerate(geoms)
		if keys[i]!=site),key=lambda item:item[0])[:max_examples]
	return {"segments":len(keys),"zero_length":zero,
		"unique_vertices":len(incidence),
		"vertex_degree_counts":{str(k):v for k,v in sorted(junctions.items())},
		"close_nonvertex_pairs_within_m":tolerance_m,
		"close_nonvertex_pairs":pairs_close,"close_examples":examples,
		"suspect_nearest":[{"edge_id":owners[keys[i]],
			"distance_m":round(d,6)} for d,i in near],
		"origin":list(origin)}


def investigate(cache,aoi,suspects,out,*,timeout=15,tolerance=0.01):
	if timeout<=0 or not math.isfinite(timeout):
		raise ValueError("Timeout muss positiv und endlich sein")
	if tolerance<0 or not math.isfinite(tolerance):
		raise ValueError("Toleranz muss nichtnegativ und endlich sein")
	out=Path(out)
	if out.exists():
		raise FileExistsError(f"Bericht existiert bereits: {out}")
	owners,origin=_noded_segments(_axes(cache),
		progress=lambda message:print(message,flush=True))
	base,extra=_read_candidate_geojson(suspects,owners,origin)
	if len(extra)!=1:
		raise ValueError("Erwartet genau ein isoliertes Problemssegment")
	site=extra[0]
	frame=_frame(load_aoi(aoi),origin)
	all_sites=base+[site]
	report={"schema":"boost-voronoi-numeric-diagnostics-v1",
		"source":str(suspects),"base_segments":len(base),
		"suspect_edge_id":owners[site],
		"timeout_s":timeout,"tolerance_m":tolerance,
		"tests":[]}
	def save():
		_save(out,report)
	def probe(name,keys,frame,change):
		print(f"Boost-Diagnose {name}: {len(keys):,} Segmente",flush=True)
		result=_timed_construct(keys,frame,timeout)
		row={"name":name,"change":change,**result}
		report["tests"].append(row)
		save()
		print(f"  {result['status']} ({result['wall_s']:.3f}s)",flush=True)
		return result
	probe("original",all_sites,frame,{"kind":"control"})
	probe("base_only",base,frame,{"kind":"control"})
	for name,ordered in _order_cases(base,site)[1:]:
		probe(name,ordered,frame,{"kind":"site_order"})
	# Translate both the segment coordinates and the enclosing frame.
	# Coordinates are 1mm integer units: 1_000_000 = 1km.
	for name,shift in (("shift_plus_1km",(1000000,1000000)),
			("shift_minus_1km",(-1000000,-1000000)),
			("shift_x_10km",(10000000,0))):
		k,f=_transform(all_sites,frame,dx=shift[0],dy=shift[1])
		probe(name,k,f,{"kind":"translation","dx_mm":shift[0],
			"dy_mm":shift[1]})
	for factor in (2,4):
		k,f=_transform(all_sites,frame,multiplier=factor)
		probe(f"scale_x{factor}",k,f,
			{"kind":"uniform_scale","factor":factor})
	print("Segmentgeometrie prüfen ...",flush=True)
	report["geometry"]=_geometry_report(all_sites,owners,origin,site,
		tolerance_m=tolerance)
	save()
	print(f"Bericht: {out}",flush=True)
	return report


def main():
	p=argparse.ArgumentParser(description=__doc__)
	p.add_argument("--cache",type=Path,required=True)
	p.add_argument("--aoi",type=Path,required=True)
	p.add_argument("--suspects",type=Path,required=True)
	p.add_argument("--out",type=Path,required=True)
	p.add_argument("--timeout",type=float,default=15)
	p.add_argument("--tolerance",type=float,default=0.01)
	a=p.parse_args()
	investigate(a.cache,a.aoi,_resolve_resume_path(a.suspects),
		a.out,timeout=a.timeout,tolerance=a.tolerance)


if __name__=="__main__":
	main()
