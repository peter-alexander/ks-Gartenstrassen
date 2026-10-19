"""Translation invariance of Boost segment Voronoi on a failing Vienna subset.

Runs each native Construct in a killable child process. Compare back-transformed
finite linear edges and vertices; curved/infinite edges and cell areas are NOT
claimed geometrically equivalent by this diagnostic.
"""
import argparse
from collections import Counter
import hashlib
import math
import multiprocessing as mp
import os
import pickle
import tempfile
from pathlib import Path
from time import perf_counter
import traceback

from scripts.benchmark_segment_voronoi import _save
from scripts.build_segment_voronoi_geojson import _axes
from scripts.diagnose_boost_voronoi import _frame, _read_candidate_geojson, _resolve_resume_path
from scripts.segment_voronoi_engine import SCALE, _noded_segments
from scripts.wienwide_grid import load_aoi


def _case(keys,frame,name,dx,dy,*,move_sites=True,move_frame=True):
	"""Translations are exact integer millimetres for sites and metres for frame."""
	if not isinstance(dx,int) or not isinstance(dy,int):
		raise ValueError("Verschiebungen müssen ganzzahlige Millimeter sein")
	sites=[((a[0]+dx,a[1]+dy),(b[0]+dx,b[1]+dy))
		for a,b in keys] if move_sites else list(keys)
	boundary=[(x+dx/SCALE,y+dy/SCALE) for x,y in frame] if move_frame else list(frame)
	undo=(dx/SCALE,dy/SCALE) if move_sites else (0.,0.)
	return {"name":name,"sites":sites,"frame":boundary,
		"undo":undo,"dx_mm":dx,"dy_mm":dy,
		"move_sites":move_sites,"move_frame":move_frame}


def _signature(pv,undo,precision):
	"""Undirected, finite, straight-edge geometry in fixed unshifted coordinates."""
	ux,uy=undo
	vertices=[(v.X-ux,v.Y-uy) for _,v in pv.EnumerateVertices()]
	def snap(point):
		return (round(point[0]/precision),round(point[1]/precision))
	vertex_set={snap(p) for p in vertices}
	linear=set()
	curved=0
	infinite=0
	primary=0
	for _,edge in pv.EnumerateEdges():
		if edge.is_primary:
			primary+=1
		if edge.start<0 or edge.end<0:
			infinite+=1
			continue
		if not edge.is_linear:
			curved+=1
			continue
		pair=tuple(sorted((snap(vertices[edge.start]),
			snap(vertices[edge.end]))))
		linear.add(pair)
	# Directed twins deliberately deduplicated; do not conflate edge counts
	# with this undirected finite-linear geometric comparison.
	return {"vertices":vertex_set,"finite_linear":linear,
		"raw_vertices":len(vertices),"raw_edges":pv.CountEdges(),
		"raw_cells":pv.CountCells(),"directed_curved_finite":curved,
		"directed_infinite":infinite,"directed_primary":primary}


def _worker(case,precision,result_path):
	try:
		import pyvoronoi
		pv=pyvoronoi.Pyvoronoi(SCALE)
		for a,b in case["sites"]:
			pv.AddSegment([[a[0]/SCALE,a[1]/SCALE],
				[b[0]/SCALE,b[1]/SCALE]])
		for a,b in zip(case["frame"],case["frame"][1:]+case["frame"][:1]):
			pv.AddSegment([list(a),list(b)])
		start=perf_counter()
		pv.Construct()
		construct=round(perf_counter()-start,5)
		data=_signature(pv,case["undo"],precision)
		with open(result_path,"wb") as handle:
			pickle.dump({"status":"ok","construct_s":construct,**data},handle,
				protocol=pickle.HIGHEST_PROTOCOL)
	except BaseException:
		with open(result_path,"wb") as handle:
			pickle.dump({"status":"error","traceback":traceback.format_exc()},handle)


def _timed(case,precision,timeout):
	if os.name!="posix":
		raise RuntimeError("Erfordert Linux/WSL mit fork")
	ctx=mp.get_context("fork")
	with tempfile.TemporaryDirectory(prefix="boost-translation-") as tmp:
		result_path=Path(tmp)/"result.pickle"
		proc=ctx.Process(target=_worker,args=(case,precision,str(result_path)))
		start=perf_counter()
		proc.start()
		proc.join(timeout)
		duration=round(perf_counter()-start,3)
		if proc.is_alive():
			proc.terminate()
			proc.join(3)
			if proc.is_alive():
				proc.kill()
				proc.join()
			return {"status":"timeout","wall_s":duration}
		if not result_path.exists():
			return {"status":"crashed","wall_s":duration,
				"exitcode":proc.exitcode}
		with result_path.open("rb") as handle:
			result=pickle.load(handle)
		return {"wall_s":duration,**result}

def _digest(items):
	sha=hashlib.sha256()
	for item in sorted(items):
		sha.update(repr(item).encode("ascii"))
		sha.update(b"\n")
	return sha.hexdigest()


def _comparison(result,reference):
	if result["status"]!="ok" or reference["status"]!="ok":
		return {"status":"not_comparable"}
	comparison={}
	for field in ("vertices","finite_linear"):
		a=result[field]
		b=reference[field]
		comparison[field]={"equal":a==b,"common":len(a&b),
			"only_case":len(a-b),"only_reference":len(b-a),
			"case_sha256":_digest(a),"reference_sha256":_digest(b)}
	return {"status":"compared","metrics":comparison,
		"note":"Only finite straight edges and finite vertices are compared. "
			"Curved/infinite edges and cell areas require full boundary reconstruction."}


def _serialize(result):
	if result["status"]!="ok":
		return result
	return {k:(_digest(v) if isinstance(v,set) else v)
		for k,v in result.items()}


def investigate(cache,aoi,suspects,out,*,timeout=15,precision=0.01):
	if timeout<=0 or not math.isfinite(timeout):
		raise ValueError("Timeout muss positiv und endlich sein")
	if precision<=0 or not math.isfinite(precision):
		raise ValueError("Vergleichstoleranz muss positiv und endlich sein")
	out=Path(out)
	if out.exists():
		raise FileExistsError(f"Ergebnisdatei existiert schon: {out}")
	owners,origin=_noded_segments(_axes(cache),
		progress=lambda m:print(m,flush=True))
	base,extra=_read_candidate_geojson(suspects,owners,origin)
	if len(extra)!=1:
		raise ValueError("Genau ein isoliertes Problemsegment erforderlich")
	sites=base+extra
	frame=_frame(load_aoi(aoi),origin)
	# Controls first, then sub-metre, medium and large translations.
	cases=[_case(sites,frame,"original",0,0)]
	for name,dx,dy in (
			("both_plus_1mm",1,1),
			("both_plus_1cm",10,10),
			("both_plus_1m",1000,1000),
			("both_plus_100m",100000,100000),
			("both_plus_1km",1000000,1000000),
			("both_minus_1km",-1000000,-1000000),
			("both_x_plus_10km",10000000,0)):
		cases.append(_case(sites,frame,name,dx,dy))
	# Separately isolate the enclosing frame: modifying only the frame is
	# NOT a pure translation and must be labelled accordingly.
	for dx,dy,suffix in ((1000000,1000000,"plus_1km"),
			(-1000000,-1000000,"minus_1km")):
		cases.append(_case(sites,frame,"frame_only_"+suffix,
			dx,dy,move_sites=False))
		cases.append(_case(sites,frame,"sites_only_"+suffix,
			dx,dy,move_frame=False))
	report={"schema":"boost-voronoi-translation-invariance-v1",
		"source":str(suspects),"baseline_segments":len(base),
		"problem_edge_id":owners[extra[0]],"timeout_s":timeout,
		"comparison_grid_m":precision,
		"comparison_scope":"undirected finite straight edges and finite vertices",
		"cell_area_comparison":"not_available_without_clipped_curved_cell_polygons",
		"cases":[]}
	results={}
	for case in cases:
		print(f"Boost {case['name']} ({len(sites):,} Linien, {timeout:g}s Limit)",
			flush=True)
		raw=_timed(case,precision,timeout)
		results[case["name"]]=raw
		entry={"name":case["name"],"dx_mm":case["dx_mm"],
			"dy_mm":case["dy_mm"],"move_sites":case["move_sites"],
			"move_frame":case["move_frame"],
			"result":_serialize(raw)}
		report["cases"].append(entry)
		_save(out,report)
		print(f"  {raw['status']} nach {raw['wall_s']:.3f}s",flush=True)
	# The unshifted run hangs; compare all successful pure translations
	# directly to the +1km control without storing massive geometries on disk.
	reference=results["both_plus_1km"]
	if reference["status"]=="ok":
		for entry in report["cases"]:
			name=entry["name"]
			if (entry["result"]["status"]=="ok" and
					entry["move_sites"] and entry["move_frame"]):
				entry["comparison_to_both_plus_1km"]=_comparison(
					results[name],reference)
	else:
		report["comparison_error"]="reference translation +1km did not complete"
	_save(out,report)
	print(f"Bericht: {out}",flush=True)
	return report


def main():
	p=argparse.ArgumentParser(description=__doc__)
	p.add_argument("--cache",type=Path,required=True)
	p.add_argument("--aoi",type=Path,required=True)
	p.add_argument("--suspects",type=Path,required=True)
	p.add_argument("--out",type=Path,required=True)
	p.add_argument("--timeout",type=float,default=15)
	p.add_argument("--precision",type=float,default=0.01)
	a=p.parse_args()
	investigate(a.cache,a.aoi,_resolve_resume_path(a.suspects),
		a.out,timeout=a.timeout,precision=a.precision)


if __name__=="__main__":
	main()
