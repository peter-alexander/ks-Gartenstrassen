"""Find a small subset triggering slow Boost segment-site Voronoi.

Uses the exact noded Vienna segments and the same distant frame as production.
Every candidate is tested in a separate process with a hard timeout.
Timeout is a symptom, not proof of malformed geometry.
"""
import argparse
import json
import math
from pathlib import Path
from time import perf_counter

from shapely.geometry import mapping, LineString

from scripts.benchmark_segment_voronoi import _samples, _timed_construct, _save
from scripts.build_segment_voronoi_geojson import _axes
from scripts.segment_voronoi_engine import SCALE, _noded_segments
from scripts.wienwide_grid import load_aoi


def _frame(aoi,origin):
	x0,y0=origin
	minx,miny,maxx,maxy=aoi.bounds
	margin=max(1000,4*math.hypot(maxx-minx,maxy-miny))
	return [(minx-margin-x0,miny-margin-y0),
		(maxx+margin-x0,miny-margin-y0),
		(maxx+margin-x0,maxy+margin-y0),
		(minx-margin-x0,maxy+margin-y0)]


def _candidate_geojson(path,base,extra,owners,origin):
	"""Save the exact suspect input, including base and site ownership."""
	x0,y0=origin
	features=[]
	for group,keys in (("base",base),("suspect",extra)):
		for key in keys:
			a,b=key
			geom=LineString(((a[0]/SCALE+x0,a[1]/SCALE+y0),
				(b[0]/SCALE+x0,b[1]/SCALE+y0)))
			features.append({"type":"Feature",
				"properties":{"edge_id":owners[key],"group":group},
				"geometry":mapping(geom)})
	path=Path(path)
	path.parent.mkdir(parents=True,exist_ok=True)
	tmp=path.with_suffix(path.suffix+".tmp")
	tmp.write_text(json.dumps({"type":"FeatureCollection",
		"crs":{"type":"name","properties":{"name":"EPSG:31256"}},
		"features":features},ensure_ascii=False,separators=(",",":")),
		encoding="utf-8")
	tmp.replace(path)


def minimize(base,additional,frame,test,*,max_tests=30,progress=None):
	"""Conservative delta debugging for interactions between segments.

	The invariant is that base+suspect remains slow. Try removing halves,
	then smaller partitions. If no individual half reproduces a timeout,
	test complements; if neither does, stop with a combined-interaction
	result, never mislabel a single segment as the cause.
	"""
	suspect=list(additional)
	history=[]
	runs=0
	def probe(candidate,kind):
		nonlocal runs
		if runs>=max_tests:
			return None
		runs+=1
		result=test(base+candidate,frame)
		row={"test":runs,"kind":kind,"suspect_segments":len(candidate),
			**result}
		history.append(row)
		if progress is not None:
			progress(row,suspect)
		return result["status"]=="timeout"
	grain=2
	stop_reason="cannot_reduce"
	while len(suspect)>1 and runs<max_tests:
		size=math.ceil(len(suspect)/grain)
		chunks=[suspect[i:i+size] for i in range(0,len(suspect),size)]
		reduced=False
		for part in chunks:
			is_slow=probe(part,"subset")
			if is_slow is None:
				break
			if is_slow:
				suspect=part
				grain=2
				reduced=True
				break
		if reduced:
			continue
		for part in chunks:
			dropped=set(part)
			complement=[key for key in suspect if key not in dropped]
			if not complement:
				continue
			is_slow=probe(complement,"complement")
			if is_slow is None:
				break
			if is_slow:
				suspect=complement
				grain=max(2,grain-1)
				reduced=True
				break
		if reduced:
			continue
		if grain>=len(suspect):
			stop_reason="interaction_or_threshold"
			break
		grain=min(len(suspect),grain*2)
	if len(suspect)==1:
		stop_reason="single_segment_with_base"
	elif runs>=max_tests:
		stop_reason="test_budget"
	return suspect,history,stop_reason


def diagnose(cache,aoi_path,out,*,baseline=50000,failing=55000,
		timeout=15,max_tests=30):
	if not (0<baseline<failing):
		raise ValueError("baseline muss kleiner als failing sein")
	if timeout<=0 or max_tests<1:
		raise ValueError("timeout und max_tests müssen positiv sein")
	axes=_axes(cache)
	t0=perf_counter()
	owners,origin=_noded_segments(axes,progress=lambda m:print(m,flush=True))
	keys=sorted(owners)
	if failing>len(keys):
		raise ValueError(f"Nur {len(keys)} Segmente vorhanden")
	ordered=_samples(keys,failing,"near")
	# IMPORTANT: _samples() is nested for near, since center comes from all keys.
	base=ordered[:baseline]
	extra=ordered[baseline:]
	frame=_frame(load_aoi(aoi_path),origin)
	out=Path(out)
	geojson=out.with_name(out.stem+"_suspects.geojson")
	report={"schema":"boost-segment-voronoi-ddmin-v1",
		"segments_total":len(keys),"baseline":baseline,"failing":failing,
		"timeout_s":timeout,"max_tests":max_tests,
		"preparation_s":round(perf_counter()-t0,2),"tests":[]}
	def save():
		_save(out,report)
	def check(candidate,frame):
		return _timed_construct(candidate,frame,timeout)
	print(f"Diagnose: Basis {baseline:,}, zusätzlich {len(extra):,}; "
		f"Timeout {timeout:g} s",flush=True)
	base_result=check(base,frame)
	report["baseline_result"]=base_result
	save()
	print(f"  Basis: {base_result['status']}",flush=True)
	if base_result["status"]!="ok":
		raise RuntimeError("Basis ist nicht schnell; Diagnose mit kleinerer Basis wiederholen")
	full_result=check(base+extra,frame)
	report["failing_result"]=full_result
	save()
	print(f"  Gesamtauswahl: {full_result['status']}",flush=True)
	if full_result["status"]!="timeout":
		report["stop_reason"]="failure_not_reproduced"
		save()
		return report
	def on_progress(row,suspect):
		report["tests"].append(row)
		report["current_suspect_count"]=len(suspect)
		save()
		print(f"  Test {row['test']}/{max_tests}: "
			f"{row['kind']}, {row['suspect_segments']:,} zusätzliche "
			f"Segmente -> {row['status']} "
			f"({row['wall_s']:.2f} s)",flush=True)
	suspect,history,reason=minimize(base,extra,frame,check,
		max_tests=max_tests,progress=on_progress)
	report["stop_reason"]=reason
	report["suspect_count"]=len(suspect)
	report["suspect_ids"]=sorted({owners[key] for key in suspect})
	report["suspect_geojson"]=str(geojson)
	_candidate_geojson(geojson,base,suspect,owners,origin)
	save()
	print(f"Diagnose: {len(suspect):,} zusätzliche Segmente, "
		f"{len(report['suspect_ids']):,} edge_id; {reason}",flush=True)
	print(f"Bericht: {out}\nGeometrien: {geojson}",flush=True)
	return report


def main():
	p=argparse.ArgumentParser(description=__doc__)
	p.add_argument("--cache",required=True,type=Path)
	p.add_argument("--aoi",required=True,type=Path)
	p.add_argument("--out",required=True,type=Path)
	p.add_argument("--baseline",type=int,default=50000)
	p.add_argument("--failing",type=int,default=55000)
	p.add_argument("--timeout",type=float,default=15)
	p.add_argument("--max-tests",type=int,default=30)
	a=p.parse_args()
	diagnose(a.cache,a.aoi,a.out,baseline=a.baseline,
		failing=a.failing,timeout=a.timeout,max_tests=a.max_tests)


if __name__=="__main__":
	main()
