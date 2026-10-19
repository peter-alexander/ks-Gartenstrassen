"""Run the independent CGAL segment-Delaunay benchmark on Vienna's noded sites.

No production files are changed. Each native run is timeout-controlled.
"""
import argparse
import json
import math
from pathlib import Path
import subprocess
from time import perf_counter

from scripts.benchmark_segment_voronoi import _save
from scripts.build_segment_voronoi_geojson import _axes
from scripts.diagnose_boost_voronoi import _frame, _read_candidate_geojson
from scripts.segment_voronoi_engine import SCALE, _noded_segments
from scripts.wienwide_grid import load_aoi


def _payload(keys,frame=(),dx=0,dy=0):
	"""Exact integer-millimetre sites; include the same frame as Boost when requested."""
	lines=[]
	for a,b in keys:
		if a==b:
			raise ValueError("Nullsegment")
		lines.append(f"{a[0]+dx} {a[1]+dy} {b[0]+dx} {b[1]+dy}")
	for a,b in zip(frame,frame[1:]+frame[:1]):
		# Frame coordinates were expressed in metres relative to the origin.
		ax,ay=round(a[0]*SCALE),round(a[1]*SCALE)
		bx,by=round(b[0]*SCALE),round(b[1]*SCALE)
		lines.append(f"{ax+dx} {ay+dy} {bx+dx} {by+dy}")
	return "\n".join(lines)+"\n"


def _run(executable,payload,timeout,validate):
	command=[str(executable)]
	if validate:
		command.append("--validate")
	start=perf_counter()
	try:
		run=subprocess.run(command,input=payload,text=True,capture_output=True,
			timeout=timeout,check=False)
	except subprocess.TimeoutExpired:
		return {"status":"timeout","wall_s":round(perf_counter()-start,3)}
	result={"wall_s":round(perf_counter()-start,3),
		"exit_code":run.returncode}
	if run.stdout.strip():
		try:
			result.update(json.loads(run.stdout.strip()))
		except json.JSONDecodeError:
			result["status"]="malformed_output"
			result["stdout_tail"]=run.stdout[-2000:]
	else:
		result["status"]="crashed"
	if run.stderr:
		result["stderr_tail"]=run.stderr[-2000:]
	if run.returncode!=0 and result.get("status")=="ok":
		result["status"]="error_exit"
	return result


def benchmark(cache,aoi,suspects,executable,out,*,timeout=30,full=False,
		validate=False,only_full=False):
	if not math.isfinite(timeout) or timeout<=0:
		raise ValueError("timeout muss positiv und endlich sein")
	if only_full and not full:
		raise ValueError("--only-full benötigt --full")
	if not Path(executable).is_file():
		raise FileNotFoundError(f"CGAL-Binary fehlt: {executable}")
	if Path(out).exists():
		raise FileExistsError(f"Bericht existiert: {out}")
	owners,origin=_noded_segments(_axes(cache),
		progress=lambda m:print(m,flush=True))
	base,extra=_read_candidate_geojson(suspects,owners,origin)
	if len(extra)!=1:
		raise ValueError("Genau ein fixes Verdachtssegment erwartet")
	frame=_frame(load_aoi(aoi),origin)
	report={"schema":"cgal-segment-delaunay-benchmark-v1",
		"source":str(suspects),"binary":str(executable),
		"base_segments":len(base),"suspect_id":owners[extra[0]],
		"full_vienna_enabled":full,"full_only":only_full,"validate":validate,
		"timeout_s":timeout,"results":[]}
	cases=[
		("site_only",extra,(),0,0),
		("base_only",base,frame,0,0),
		("combined_no_frame",base+extra,(),0,0),
		("combined_with_frame",base+extra,frame,0,0),
		("combined_plus_1mm",base+extra,frame,1,1),
		("combined_plus_1km",base+extra,frame,1000000,1000000)]
	if only_full:
		cases=[]
	if full:
		all_keys=sorted(owners)
		cases.extend([
			("full_vienna_no_frame",all_keys,(),0,0),
			("full_vienna_with_frame",all_keys,frame,0,0),
			("full_vienna_plus_1mm",all_keys,frame,1,1),
			("full_vienna_plus_1km",all_keys,frame,1000000,1000000)])
	for name,keys,boundary,dx,dy in cases:
		print(f"CGAL {name}: {len(keys):,} Segmente",flush=True)
		result=_run(executable,_payload(keys,boundary,dx,dy),timeout,validate)
		report["results"].append({"case":name,"segments":len(keys),
			"frame_segments":len(boundary),"dx_mm":dx,"dy_mm":dy,
			**result})
		_save(out,report)
		print(f"  {result['status']}, {result['wall_s']:.3f}s",flush=True)
	# Equal graph counts are necessary, not sufficient, for geometric equivalence.
	baseline=next((row for row in report["results"]
		if row["case"]=="full_vienna_with_frame" and row["status"]=="ok"),None)
	if full:
		report["full_vienna_assessment"]={
			"reference_ok":baseline is not None,
			"all_cases_ok":all(row["status"]=="ok" for row in report["results"]),
			"translations":[]}
		for row in report["results"]:
			if row["case"] not in ("full_vienna_plus_1mm","full_vienna_plus_1km"):
				continue
			comparison={"case":row["case"],
				"comparable":baseline is not None and row["status"]=="ok"}
			if comparison["comparable"]:
				comparison["counts_equal"]={
					key:row.get(key)==baseline.get(key)
					for key in ("input_sites","output_sites","vertices","faces")}
			report["full_vienna_assessment"]["translations"].append(comparison)
		_save(out,report)
	return report


def main():
	p=argparse.ArgumentParser(description=__doc__)
	p.add_argument("--cache",type=Path,required=True)
	p.add_argument("--aoi",type=Path,required=True)
	p.add_argument("--suspects",type=Path,required=True)
	p.add_argument("--binary",type=Path,required=True)
	p.add_argument("--out",type=Path,required=True)
	p.add_argument("--timeout",type=float,default=30)
	p.add_argument("--full",action="store_true")
	p.add_argument("--only-full",action="store_true")
	p.add_argument("--validate",action="store_true")
	a=p.parse_args()
	benchmark(a.cache,a.aoi,a.suspects,a.binary,a.out,
		timeout=a.timeout,full=a.full,validate=a.validate,
		only_full=a.only_full)


if __name__=="__main__":
	main()
