"""Timed, isolated Boost segment-Voronoi benchmarks on real Wiener GIP axes.

The entire input is noded once. Boost runs are separate, timeout-controlled
processes. No GeoJSON or SIS clipping is performed by this diagnostic.
"""
import argparse
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
from time import perf_counter
import traceback

from scripts.build_segment_voronoi_geojson import _axes
from scripts.segment_voronoi_engine import SCALE, _noded_segments


def _worker(keys,frame,scale,conn):
	"""Isolated native Boost execution; never modify source data."""
	try:
		import pyvoronoi
		pv=pyvoronoi.Pyvoronoi(scale)
		for a,b in keys:
			pv.AddSegment([[a[0]/scale,a[1]/scale],
				[b[0]/scale,b[1]/scale]])
		for a,b in zip(frame,frame[1:]+frame[:1]):
			pv.AddSegment([list(a),list(b)])
		start=perf_counter()
		pv.Construct()
		conn.send({"status":"ok","construct_s":round(perf_counter()-start,4),
			"cells":len(pv.GetCells()),"edges":len(pv.GetEdges())})
	except BaseException:
		conn.send({"status":"error","traceback":traceback.format_exc()})
	finally:
		conn.close()


def _timed_construct(keys,frame,timeout,scale=SCALE):
	if os.name!="posix":
		raise RuntimeError("Benchmark benötigt Linux/WSL für isolierte fork-Prozesse")
	ctx=mp.get_context("fork")
	receiver,sender=ctx.Pipe(duplex=False)
	proc=ctx.Process(target=_worker,args=(keys,frame,scale,sender))
	start=perf_counter()
	proc.start()
	sender.close()
	proc.join(timeout)
	duration=round(perf_counter()-start,3)
	if proc.is_alive():
		proc.terminate()
		proc.join(3)
		if proc.is_alive():
			proc.kill()
			proc.join()
		receiver.close()
		return {"status":"timeout","wall_s":duration}
	if receiver.poll():
		result=receiver.recv()
	else:
		result={"status":"crashed","exitcode":proc.exitcode}
	receiver.close()
	return {"wall_s":duration,**result}


def _samples(keys,size,strategy):
	if size>=len(keys):
		return keys
	if strategy=="spread":
		# Reproducible sample of the whole city, independent of hash order.
		return [keys[i*len(keys)//size] for i in range(size)]
	# A contiguous neighborhood from the same preprocessed sites.
	center_x=sum((a[0]+b[0])/2 for a,b in keys)/len(keys)
	center_y=sum((a[1]+b[1])/2 for a,b in keys)/len(keys)
	return sorted(keys,key=lambda k:
		((k[0][0]+k[1][0])/2-center_x)**2+
		((k[0][1]+k[1][1])/2-center_y)**2)[:size]


def _save(path,report):
	path=Path(path)
	path.parent.mkdir(parents=True,exist_ok=True)
	tmp=path.with_suffix(path.suffix+".tmp")
	tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
	os.replace(tmp,path)


def benchmark(cache,out,*,sizes=(1000,5000,10000,25000,50000),
		timeout=45,strategies=("near","spread")):
	if timeout<=0 or not math.isfinite(timeout):
		raise ValueError("timeout muss positiv und endlich sein")
	print("Benchmark: LINEAR_USE lesen und einmalig noding durchführen",flush=True)
	axes=_axes(cache)
	start=perf_counter()
	noded,origin=_noded_segments(axes,progress=lambda msg:print(msg,flush=True))
	prepare_s=round(perf_counter()-start,3)
	keys=sorted(noded)
	print(f"Benchmark: {len(keys):,} Segmente in {prepare_s:.1f} s vorbereitet",flush=True)
	# Match production: same translated coordinates and same distant frame.
	x0,y0=origin
	minx=min(a[0] for a,b in keys)/SCALE+x0
	miny=min(a[1] for a,b in keys)/SCALE+y0
	maxx=max(b[0] for a,b in keys)/SCALE+x0
	maxy=max(b[1] for a,b in keys)/SCALE+y0
	diameter=math.hypot(maxx-minx,maxy-miny)
	margin=max(1000,4*diameter)
	frame=[(minx-margin-x0,miny-margin-y0),
		(maxx+margin-x0,miny-margin-y0),
		(maxx+margin-x0,maxy+margin-y0),
		(minx-margin-x0,maxy+margin-y0)]
	report={"axes":len(axes),"segments":len(keys),"noding_s":prepare_s,
		"timeout_s":timeout,"results":[]}
	_save(out,report)
	for strategy in strategies:
		for requested in sizes:
			size=min(requested,len(keys))
			if size<2:
				raise ValueError("Mindestens zwei Segmente erforderlich")
			selected=_samples(keys,size,strategy)
			print(f"Boost-Benchmark: {strategy}, {size:,} Segmente, "
				f"maximal {timeout:g} s ...",flush=True)
			result=_timed_construct(selected,frame,timeout)
			row={"strategy":strategy,"segments":size,**result}
			report["results"].append(row)
			_save(out,report)
			print(f"  {result['status']}: {result['wall_s']:.2f} s"
				+ (f" (Boost: {result['construct_s']:.2f} s)"
					if "construct_s" in result else ""),flush=True)
			if result["status"]!="ok":
				print(f"  Keine weiteren größeren Tests für {strategy}",flush=True)
				break
	print(f"Benchmark-Ergebnis: {out}",flush=True)
	return report


def main():
	p=argparse.ArgumentParser(description=__doc__)
	p.add_argument("--cache",type=Path,required=True)
	p.add_argument("--out",type=Path,required=True)
	p.add_argument("--sizes",type=int,nargs="+",
		default=[1000,5000,10000,25000,50000])
	p.add_argument("--timeout",type=float,default=45)
	p.add_argument("--strategies",nargs="+",choices=["near","spread"],
		default=["near","spread"])
	args=p.parse_args()
	benchmark(args.cache,args.out,sizes=args.sizes,
		timeout=args.timeout,strategies=args.strategies)


if __name__=="__main__":
	main()
