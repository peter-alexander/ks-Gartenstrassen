"""Compare all true Vienna neighbors with the diagnostic base and test local Boost inputs.

Diagnostic only: never changes cached geometry or production Voronoi.
"""
import argparse
import json
import math
from pathlib import Path

from shapely.geometry import LineString, mapping
from shapely.strtree import STRtree

from scripts.benchmark_segment_voronoi import _samples, _save, _timed_construct
from scripts.build_segment_voronoi_geojson import _axes
from scripts.diagnose_boost_voronoi import (
	_frame, _read_candidate_geojson, _resolve_resume_path)
from scripts.segment_voronoi_engine import SCALE, _noded_segments
from scripts.wienwide_grid import load_aoi


def _line(key):
	a,b=key
	return LineString(((a[0]/SCALE,a[1]/SCALE),
		(b[0]/SCALE,b[1]/SCALE)))


def _nearby(keys,target,radius):
	"""Return sites whose real segment-to-segment distance is <= radius."""
	if radius<0:
		raise ValueError("Radius darf nicht negativ sein")
	geoms=[_line(k) for k in keys]
	tree=STRtree(geoms)
	tgeom=_line(target)
	found=[]
	for index in tree.query(tgeom.buffer(radius).envelope):
		i=int(index)
		d=geoms[i].distance(tgeom)
		if d<=radius+1e-9:
			found.append((keys[i],d))
	return sorted(found,key=lambda item:(item[1],item[0]))


def investigate(cache,aoi_path,out,*,suspects,radii=(10,25,50,100,200,500),
		timeout=15,limit=20000,baseline=50000):
	if timeout<=0 or not math.isfinite(timeout) or limit<2:
		raise ValueError("Timeout muss positiv und Limit mindestens 2 sein")
	if not radii or any(r<=0 or not math.isfinite(r) for r in radii):
		raise ValueError("Radien müssen positiv und endlich sein")
	axes=_axes(cache)
	owners,origin=_noded_segments(axes,
		progress=lambda message:print(message,flush=True))
	keys=sorted(owners)
	if baseline>=len(keys):
		raise ValueError("Benchmarkbasis ist größer als der Datensatz")
	base=_samples(keys,baseline,"near")
	# Read exact one-site reduction from previous diagnosis, not an arbitrary
	# segment of the matching edge_id.
	saved_base,extras=_read_candidate_geojson(suspects,owners,origin)
	if len(extras)!=1:
		raise ValueError("Bitte Fortsetzungs-GeoJSON mit genau einem Verdachtssegment verwenden")
	if base!=saved_base:
		raise ValueError("Gespeicherte Benchmarkbasis stimmt nicht mit aktuellen Daten überein")
	target=extras[0]
	frames=_frame(load_aoi(aoi_path),origin)
	base_set=set(base)
	all_near=_nearby(keys,target,max(radii))
	near_rows=[]
	for key,d in all_near:
		if key==target:
			continue
		near_rows.append({"edge_id":owners[key],
			"distance_m":round(d,6),"length_m":round(_line(key).length,6),
			"in_benchmark_base":key in base_set,
			"coordinates_31256":[[round(x/SCALE+origin[0],3),
				round(y/SCALE+origin[1],3)] for x,y in key]})
	report={"schema":"boost-voronoi-neighbor-v1",
		"target_edge_id":owners[target],"target_coordinates_31256":[
			[x/SCALE+origin[0],y/SCALE+origin[1]] for x,y in target],
		"baseline":len(base),"nearby":near_rows,"tests":[]}
	out=Path(out)
	_save(out,report)
	print(f"Nachbarn innerhalb {max(radii):g} m: {len(near_rows):,}; "
		f"davon {sum(x['in_benchmark_base'] for x in near_rows):,} in Benchmarkbasis",
		flush=True)
	print("Nächste 12 Segmente:",flush=True)
	for row in near_rows[:12]:
		print(f"  {row['distance_m']:.3f} m | {row['edge_id']} | "
			f"in Basis: {row['in_benchmark_base']}",flush=True)
	# One test only on suspect, then cumulative local sets; preserve segment
	# input order from the repository site key sort to avoid changing meaning.
	cases=[("target_only",[target])]
	for radius in sorted(set(radii)):
		local={key for key,d in all_near if d<=radius}
		local.add(target)
		cases.append((f"radius_{radius:g}m",sorted(local)))
	cases.append(("baseline_plus_target",base+[target]))
	for name,selected in cases:
		if len(selected)>limit and name!="baseline_plus_target":
			result={"status":"skipped_limit","count":len(selected)}
		else:
			print(f"Boost lokal: {name}, {len(selected):,} Segmente "
				f"(maximal {timeout:g} s)",flush=True)
			result=_timed_construct(selected,frames,timeout)
		row={"name":name,"segments":len(selected),**result}
		report["tests"].append(row)
		_save(out,report)
		print(f"  {name}: {result['status']}, {result.get('wall_s','-')} s",
			flush=True)
	print(f"Diagnose: {out}",flush=True)
	return report


def main():
	p=argparse.ArgumentParser(description=__doc__)
	p.add_argument("--cache",type=Path,required=True)
	p.add_argument("--aoi",type=Path,required=True)
	p.add_argument("--out",type=Path,required=True)
	p.add_argument("--suspects",type=Path,required=True)
	p.add_argument("--radii",type=float,nargs="+",
		default=[10,25,50,100,200,500])
	p.add_argument("--timeout",type=float,default=15)
	p.add_argument("--limit",type=int,default=20000)
	a=p.parse_args()
	investigate(a.cache,a.aoi,a.out,suspects=_resolve_resume_path(a.suspects),
		radii=a.radii,timeout=a.timeout,limit=a.limit)


if __name__=="__main__":
	main()
