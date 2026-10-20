"""Native CGAL -> labelled dual -> metric polygons -> conservative face QA.

Small deterministic fixture only. This does not validate the Vienna pipeline.
Invoke from the repository root after compiling the CGAL executable.
"""
import argparse
from collections import Counter
import json
import subprocess
import tempfile
from pathlib import Path

from shapely.geometry import Point,LineString,box
from shapely.ops import unary_union

from scripts.cgal_native_adapter import metric_labelled_segments_file
from scripts.cgal_topology_proof import reconstruct_test_cells
from scripts.cgal_labelled_edges import labelled_edges_file
from scripts.cgal_unresolved_site_audit import inspect_unresolved_faces
from scripts.cgal_internal_dual_audit import audit_internal_duals


def _site_geometry(site,scale):
	kind,coordinates=site
	if kind=="P":
		return Point(coordinates[0]/scale,coordinates[1]/scale)
	return LineString(((coordinates[0]/scale,coordinates[1]/scale),
		(coordinates[2]/scale,coordinates[3]/scale)))


def verify_native_fixture(binary, *, fixture='parallel', diagnose=False):
	# Three parallel, non-intersecting segment generators. Endpoints
	# introduce point sites that a point-only Delaunay fixture misses.
	fixtures={
		"parallel":"0 0 20000 0\n0 10000 20000 10000\n0 20000 20000 20000\n",
		"junction":"0 0 20000 0\n10000 0 10000 15000\n10000 15000 20000 20000\n",
		"crossing":"0 10000 20000 10000\n10000 0 10000 20000\n",
		"oblique":"0 0 17000 9000\n0 18000 20000 15000\n5000 22000 15000 4000\n"}
	if fixture not in fixtures:
		raise ValueError(f"Unknown fixture {fixture}")
	input_lines=fixtures[fixture]
	window=box(-5,-5,25,25)
	with tempfile.TemporaryDirectory(prefix="cgal-native-test-") as temp:
		temp=Path(temp)
		command=[str(Path(binary).resolve()),"--edges",str(temp/"dual.txt"),
			"--sites",str(temp/"sites.txt"),"--labelled-edges",
			str(temp/"labelled.txt"),"--bounds","-5000","-5000","25000","25000"]
		result=subprocess.run(command,input=input_lines,text=True,
			capture_output=True,timeout=90,check=True)
		native=json.loads(result.stdout)
		if native["status"]!="ok":
			raise AssertionError(native)
		edges=list(labelled_edges_file(temp/"labelled.txt"))
		assert native["labelled_edges"]==len(edges)
		assert len(edges)>0
		segments=list(metric_labelled_segments_file(temp/"labelled.txt",window))
		assert segments,"Native CGAL fixture produced no clipped dual edges"
		polygons,labels,stats=reconstruct_test_cells(window,segments,
			diagnose=diagnose)
		assert polygons,"Native CGAL produced no polygon faces"
		assert len(polygons)==len(labels)
		assert all(p.is_valid and p.area>0 for p in polygons)
		area=unary_union(polygons)
		assert window.difference(area).area<1e-6,"Uncovered window area"
		assert sum(p.area for p in polygons)-area.area<1e-6,"Overlapping faces"
		sites=set()
		for _,pair,_ in edges:
			sites.update(pair)
		for polygon,label in zip(polygons,labels):
			if label is None:
				continue
			assert label in sites,"Unrecognized native CGAL generator"
			geometry=_site_geometry(label,1000.)
			if geometry.geom_type=="Point":
				assert polygon.covers(geometry),"Proven point site outside cell"
			else:
				assert polygon.intersects(geometry),"Proven segment site outside cell"
		# Experimental comparison; established QA remains the baseline.
		new_polygons,new_labels,new_stats=reconstruct_test_cells(
			window,segments,noded_provenance=True)
		assert len(new_polygons)==len(polygons)
		assert sum(new_stats.values())==len(polygons)
		for polygon,label in zip(new_polygons,new_labels):
			if label is not None:
				assert polygon.intersects(_site_geometry(label,1000.))
		carried_polygons,carried_labels,carried_stats=reconstruct_test_cells(
			window,segments,carried_provenance=True,diagnose=True)
		assert len(carried_polygons)==len(polygons)
		carried_stats["site_audit"]=inspect_unresolved_faces(
			carried_polygons,carried_labels,edges)
		carried_stats["internal_duals"]=audit_internal_duals(
			carried_polygons,carried_labels,segments)
		assert len(carried_stats["site_audit"])==sum(
			label is None for label in carried_labels)
		assert len(carried_stats["internal_duals"])==len(carried_stats["site_audit"])
		assert sum(value for key,value in carried_stats.items()
			if key not in ('diagnostic_examples','site_audit','internal_duals'))==len(polygons)
		for polygon,label in zip(carried_polygons,carried_labels):
			if label is not None:
				assert polygon.intersects(_site_geometry(label,1000.))
		assert sum(value for key,value in stats.items()
			if key!='diagnostic_examples')==len(polygons)
		# Baseline of real native fixtures, not a blanket quality pass.
		# Open cases remain unresolved rather than receiving guessed sites.
		expected={
			"parallel":(9,9,0,0,0),
			"junction":(8,4,2,1,1),
			"crossing":(8,8,0,0,0),
			"oblique":(6,2,0,0,4)}
		actual=(len(polygons),stats["proven"],
			stats["conflicting_labels"],stats["insufficient_incidence"],
			stats["missing_boundary_labels"])
		assert actual==expected[fixture],(fixture,actual,expected[fixture])
		return {"fixture":fixture,"native_edges":len(edges),"clipped_fragments":len(segments),
			"cells":len(polygons),**stats,"experimental_noded":new_stats,
			"experimental_carried":carried_stats}


def main():
	parser=argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--binary",type=Path,required=True)
	parser.add_argument("--diagnose",action="store_true",
		help="Include concrete unresolved face and missing-boundary geometry")
	args=parser.parse_args()
	for fixture in ("parallel","junction","crossing","oblique"):
		print(json.dumps(verify_native_fixture(args.binary,fixture=fixture,
			diagnose=args.diagnose),sort_keys=True))


if __name__=="__main__":
	main()
