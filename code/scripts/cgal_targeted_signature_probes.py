"""Independent synthetic CGAL signature probes; never ownership evidence.

These extra native geometries intentionally do not enter the fixed
seven-fixture polygon QA baseline or Vienna production pipeline.
A raw signature hit is NOT a geometrically verified regular boundary.
"""
import argparse
import json
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

TARGETS={(2,2,False,True),(1,2,False,True)}
PROBES={
	"grid_horizontal_shift":"0 0 0 20000\n10000 0 10000 20000\n20000 0 20000 20000\n0 8000 20000 8000\n",
	"grid_horizontal_reverse":"0 0 0 20000\n10000 0 10000 20000\n20000 0 20000 20000\n20000 10000 0 10000\n",
	"grid_vertical_reverse":"0 20000 0 0\n10000 20000 10000 0\n20000 20000 20000 0\n0 10000 20000 10000\n",
	"grid_sheared":"0 0 2000 20000\n10000 0 12000 20000\n20000 0 22000 20000\n0 10000 22000 12000\n",
}


def parse_signature_records(topology_lines,incidence_lines):
	"""Fail closed on missing, malformed or misordered native E records."""
	if len(topology_lines)!=len(incidence_lines):
		raise ValueError("Topology/incidence record count mismatch")
	out=[]
	for index,(top,inc) in enumerate(zip(topology_lines,incidence_lines)):
		t=top.split(maxsplit=4)
		f=inc.split(maxsplit=6)
		if (len(t)!=5 or t[:2]!=["T",str(index)] or t[2] not in ("0","1")
				or len(f)!=7 or f[:2]!=["F",str(index)]
				or any(v not in ("0","1","2") for v in f[2:4])
				or any(v not in ("0","1") for v in f[4:6])
				or not f[6].startswith("OPP ") or " | NEIGH " not in f[6]):
			raise ValueError(f"Invalid native record {index}")
		sig=(int(f[2]),int(f[3]),f[4]=="1",f[5]=="1")
		out.append({"edge_id":index,"endpoint_dual":t[2]=="1",
			"signature":list(sig),"target_signature":sig in TARGETS,
			"ownership_proven":False})
	return out


def probe(binary,name,geometry):
	with tempfile.TemporaryDirectory(prefix="cgal-signature-probe-") as tmp:
		topology=Path(tmp)/"topology.txt"
		incidence=Path(tmp)/"incidence.txt"
		command=[str(Path(binary).resolve()),"--edges",str(Path(tmp)/"edges.txt"),
			"--labelled-edges",str(Path(tmp)/"labelled.txt"),
			"--edge-topology",str(topology),"--face-incidence",str(incidence),
			"--bounds","-5000","-5000","25000","25000"]
		process=subprocess.run(command,input=geometry,text=True,capture_output=True,
			timeout=90,check=True)
		native=json.loads(process.stdout)
		if native.get("status")!="ok":
			raise ValueError("Native probe failed")
		rows=parse_signature_records(topology.read_text().splitlines(),
			incidence.read_text().splitlines())
		return {"fixture":name,"native_edges":len(rows),
			"target_hits":[r for r in rows if r["target_signature"]],
			"regular_target_hits":[r for r in rows if r["target_signature"]
				and not r["endpoint_dual"]],
			"interpretation":"raw_native_only_requires_independent_side_verification",
			"ownership_proven":False}


def main():
	parser=argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--binary",required=True)
	args=parser.parse_args()
	for name,geometry in PROBES.items():
		print(json.dumps(probe(args.binary,name,geometry),sort_keys=True))


if __name__=="__main__":
	main()
