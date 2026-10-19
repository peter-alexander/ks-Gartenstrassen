"""Reverse Boost delta debugging: keep one suspect and reduce its 50k baseline.

No geometry modifications or production export. All tests preserve the exact
relative site order used in the earlier reproducing benchmark.
"""
import argparse
import math
from pathlib import Path
from time import perf_counter

from scripts.benchmark_segment_voronoi import _save, _timed_construct
from scripts.build_segment_voronoi_geojson import _axes
from scripts.diagnose_boost_voronoi import (
	_candidate_geojson, _frame, _read_candidate_geojson, minimize,
	_resolve_resume_path)
from scripts.segment_voronoi_engine import _noded_segments
from scripts.wienwide_grid import load_aoi


def _reproduce_order(original_base,site,selected):
	"""Maintain the previous Boost insertion order: base followed by suspect."""
	selected_set=set(selected)
	if len(selected_set)!=len(selected) or not selected_set.issubset(set(original_base)):
		raise ValueError("Ungültige Segmentauswahl")
	return [key for key in original_base if key in selected_set]+[site]


def reverse_diagnose(cache,aoi_path,suspects,out,*,timeout=15,max_tests=60):
	if not math.isfinite(timeout) or timeout<=0 or max_tests<1:
		raise ValueError("Timeout und Testbudget müssen positiv sein")
	print("LINEAR_USE für umgekehrte Boost-Diagnose aufbereiten",flush=True)
	start=perf_counter()
	owners,origin=_noded_segments(_axes(cache),
		progress=lambda message:print(message,flush=True))
	base,extra=_read_candidate_geojson(suspects,owners,origin)
	if len(extra)!=1:
		raise ValueError("Benötigt genau ein isoliertes Verdachtssegment")
	site=extra[0]
	frame=_frame(load_aoi(aoi_path),origin)
	out=Path(out)
	geojson=out.with_name(out.stem+"_minimal.geojson")
	report={"schema":"boost-segment-voronoi-reverse-ddmin-v1",
		"isolated_edge_id":owners[site],
		"initial_base_segments":len(base),"timeout_s":timeout,
		"max_tests":max_tests,"preparation_s":round(perf_counter()-start,3),
		"source":str(suspects),"tests":[]}
	def save():
		_save(out,report)
	def timed(candidate):
		return _timed_construct(candidate,frame,timeout)
	print(f"Basis: {len(base):,} Segmente; fixes Segment: "
		f"{owners[site]}",flush=True)
	alone=timed([site])
	report["site_only"]=alone
	save()
	if alone["status"]!="ok":
		raise RuntimeError("Verdachtssegment alleine bereits auffällig")
	baseline=timed(base)
	report["baseline_only"]=baseline
	save()
	if baseline["status"]!="ok":
		raise RuntimeError("Benchmarkbasis alleine ist nicht mehr schnell")
	combined=timed(base+[site])
	report["initial_combined"]=combined
	save()
	if combined["status"]!="timeout":
		report["stop_reason"]="not_reproduced"
		save()
		raise RuntimeError("Ursprünglicher Timeout nicht reproduzierbar")
	# minimize() keeps its first argument fixed; reverse the roles.
	# Its internal test receives [site] + selected_baseline. Restore
	# the ORIGINAL site ordering before every native Boost call.
	def ordered_test(candidate,_frame_unused):
		if candidate[0]!=site:
			raise ValueError("Fixes Verdachtssegment fehlt")
		return timed(_reproduce_order(base,site,candidate[1:]))
	def progress(row,current):
		report["tests"].append(row)
		save()
		print(f"  Versuch {row['test']}/{max_tests}: "
			f"{row['kind']} {row['suspect_segments']:,} Basissegmente "
			f"=> {row['status']} ({row['wall_s']:.2f} s)",flush=True)
	minimal,history,reason=minimize([site],base,frame,ordered_test,
		max_tests=max_tests,progress=progress)
	confirmed=timed(_reproduce_order(base,site,minimal))
	report["final_verification"]=confirmed
	report["remaining_base_segments"]=len(minimal)
	report["stop_reason"]=reason
	report["minimal_geojson"]=str(geojson)
	report["remaining_edge_ids"]=sorted({owners[key] for key in minimal})
	_candidate_geojson(geojson,minimal,[site],owners,origin)
	save()
	print(f"Ergebnis: {len(minimal):,} Basissegmente verblieben, "
		f"Bestätigung={confirmed['status']}; {reason}",flush=True)
	print(f"JSON: {out}\nGeoJSON: {geojson}",flush=True)
	return report


def main():
	p=argparse.ArgumentParser(description=__doc__)
	p.add_argument("--cache",type=Path,required=True)
	p.add_argument("--aoi",type=Path,required=True)
	p.add_argument("--suspects",type=Path,required=True)
	p.add_argument("--out",type=Path,required=True)
	p.add_argument("--timeout",type=float,default=15)
	p.add_argument("--max-tests",type=int,default=60)
	a=p.parse_args()
	reverse_diagnose(a.cache,a.aoi,_resolve_resume_path(a.suspects),
		a.out,timeout=a.timeout,max_tests=a.max_tests)


if __name__=="__main__":
	main()
