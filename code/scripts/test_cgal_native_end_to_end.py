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
from shapely.ops import unary_union,polygonize

from scripts.cgal_native_adapter import metric_labelled_segments_file
from scripts.build_cgal_voronoi_geojson import _record_line
from scripts.cgal_topology_proof import reconstruct_test_cells
from scripts.cgal_labelled_edges import labelled_edges_file
from scripts.cgal_unresolved_site_audit import inspect_unresolved_faces
from scripts.cgal_internal_dual_audit import audit_internal_duals
from scripts.cgal_subface_validation import inspect_subfaces
from scripts.cgal_repair_test_cells import repair_test_cells
from scripts.cgal_grid_conflict_audit import audit_conflicting_faces
from scripts.cgal_directed_boundary_audit import directed_face_edges
from scripts.cgal_directed_boundary_audit import directed_face_edges,audit_boundary_sides
from scripts.cgal_pair_constraints import audit_pair_constraints
from scripts.cgal_shared_boundary_audit import audit_shared_boundaries
from scripts.cgal_native_source_audit import audit_native_shared_sources
from scripts.cgal_degenerate_ray_sides import audit_degenerate_ray_sides


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
		"oblique":"0 0 17000 9000\n0 18000 20000 15000\n5000 22000 15000 4000\n",
		"fan":"10000 10000 10000 22000\n10000 10000 22000 10000\n10000 10000 2000 2000\n",
		"grid":"0 0 0 20000\n10000 0 10000 20000\n20000 0 20000 20000\n0 10000 20000 10000\n",
		"near_parallel":"0 0 20000 200\n0 3000 20000 3300\n0 8000 20000 8300\n"}
	if fixture not in fixtures:
		raise ValueError(f"Unknown fixture {fixture}")
	input_lines=fixtures[fixture]
	window=box(-5,-5,25,25)
	with tempfile.TemporaryDirectory(prefix="cgal-native-test-") as temp:
		temp=Path(temp)
		command=[str(Path(binary).resolve()),"--edges",str(temp/"dual.txt"),
			"--sites",str(temp/"sites.txt"),"--labelled-edges",
			str(temp/"labelled.txt"),"--edge-topology",
			str(temp/"topology.txt"),"--skeleton-edge-ids",
			str(temp/"skeleton_ids.txt"),"--skeleton",str(temp/"skeleton.txt"),"--bounds","-5000","-5000","25000","25000"]
		result=subprocess.run(command,input=input_lines,text=True,
			capture_output=True,timeout=90,check=True)
		native=json.loads(result.stdout)
		if native["status"]!="ok":
			raise AssertionError(native)
		edges=list(labelled_edges_file(temp/"labelled.txt"))
		assert native["labelled_edges"]==len(edges)
		topology=(temp/"topology.txt").read_text(encoding="utf-8").splitlines()
		assert len(topology)==len(edges)
		endpoint_ids=[]
		for index,record in enumerate(topology):
			fields=record.split(maxsplit=4)
			assert fields[:2]==["T",str(index)]
			assert fields[2] in ("0","1") and fields[3]=="CW"
			assert " | CCW " in fields[4]
			if fields[2]=="1":
				endpoint_ids.append(index)
		assert native["endpoint_duals"]==len(endpoint_ids)
		flags=(temp/"skeleton_ids.txt").read_text(encoding="utf-8").splitlines()
		assert len(flags)==len(edges)
		excluded_ids=[]
		for index,record in enumerate(flags):
			assert record in (f"K {index} 0",f"K {index} 1")
			if record.endswith(" 0"):
				excluded_ids.append(index)
		assert excluded_ids==endpoint_ids
		skeleton_lines=[]
		for record in (temp/"skeleton.txt").read_text(encoding="utf-8").splitlines():
			fields=record.split()
			assert fields[0] in ("S","R","L") and len(fields)==5
			coords=[float(value)/1000. for value in fields[1:]]
			shape=_record_line(fields[0],
				((coords[0],coords[1]),(coords[2],coords[3])),window)
			if shape is not None and not shape.is_empty:
				skeleton_lines.extend(shape.geoms if hasattr(shape,"geoms")
					else [shape])
		

		assert len(edges)>0
		segments=list(metric_labelled_segments_file(temp/"labelled.txt",window))
		assert segments,"Native CGAL fixture produced no clipped dual edges"
		full_lines=[line for line,_ in segments]
		full_union=unary_union(full_lines)
		skeleton_union=unary_union(skeleton_lines)
		skeleton_outside=skeleton_union.difference(full_union).length
		# The native per-E skeleton eligibility flag is verified against
		# independently emitted CGAL skeleton geometry (not merely labels).
		kept_sources=[]
		for edge_id,pair,fragments in edges:
			if edge_id in endpoint_ids:
				continue
			for kind,values in fragments:
				coords=[value/1000. for value in values]
				shape=_record_line(kind,
					((coords[0],coords[1]),(coords[2],coords[3])),window)
				if shape is not None and not shape.is_empty:
					kept_sources.extend(shape.geoms if hasattr(shape,"geoms")
						else [shape])
		kept_union=unary_union(kept_sources)
		skeleton_to_kept=skeleton_union.difference(kept_union).length
		kept_to_skeleton=kept_union.difference(skeleton_union).length
		assert skeleton_to_kept<1e-8 and kept_to_skeleton<1e-8, (
			fixture,skeleton_to_kept,kept_to_skeleton)
		skeleton_removed=full_union.difference(skeleton_union).length
		skeleton_faces=list(polygonize(unary_union([window.boundary,*skeleton_lines])))
		skeleton_covered=unary_union(skeleton_faces)
		
		skeleton_gap=window.difference(skeleton_covered).area
		if fixture=="grid":
			assert len(skeleton_faces)==6
			assert skeleton_removed>0
			assert skeleton_outside<1e-6

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
				assert polygon.distance(geometry)<=1e-8,"Proven point site outside cell"
			else:
				assert polygon.distance(geometry)<=1e-8,"Proven segment site outside cell"
		# Experimental comparison; established QA remains the baseline.
		new_polygons,new_labels,new_stats=reconstruct_test_cells(
			window,segments,noded_provenance=True)
		assert len(new_polygons)==len(polygons)
		assert sum(new_stats.values())==len(polygons)
		for polygon,label in zip(new_polygons,new_labels):
			if label is not None:
				assert polygon.distance(_site_geometry(label,1000.))<=1e-8
		carried_polygons,carried_labels,carried_stats=reconstruct_test_cells(
			window,segments,carried_provenance=True,diagnose=True)
		assert len(carried_polygons)==len(polygons)
		carried_stats["site_audit"]=inspect_unresolved_faces(
			carried_polygons,carried_labels,edges)
		carried_stats["internal_duals"]=audit_internal_duals(
			carried_polygons,carried_labels,segments)
		if fixture=="grid":
			carried_stats["grid_conflicts"]=audit_conflicting_faces(
				carried_polygons,carried_labels,segments)
			carried_stats["pair_constraints"]=audit_pair_constraints(
				carried_polygons,carried_labels,segments)
			carried_stats["shared_boundary_audit"]=audit_shared_boundaries(
				carried_polygons,carried_labels,segments)
			carried_stats["native_source_audit"]=audit_native_shared_sources(
				carried_stats["shared_boundary_audit"],edges,segments,window)
			carried_stats["degenerate_ray_sides"]=audit_degenerate_ray_sides(
				carried_stats["native_source_audit"])
			for finding in carried_stats["degenerate_ray_sides"]:
				assert set(finding["native_edge_ids"]).issubset(endpoint_ids)
			carried_stats["directed_boundary"]=directed_face_edges(
				carried_polygons,carried_labels,segments,
				face_ids=[item["face_index"] for item
					in carried_stats["grid_conflicts"]])
			carried_stats["boundary_sides"]=audit_boundary_sides(
				carried_polygons,carried_labels,segments,
				face_ids=[item["face_index"] for item
					in carried_stats["grid_conflicts"]])
		if fixture=="oblique":
			target=carried_stats["internal_duals"][0]["face_index"]
			carried_stats["subface_validation"]=inspect_subfaces(
				carried_polygons[target],segments)
		assert len(carried_stats["site_audit"])==sum(
			label is None for label in carried_labels)
		assert len(carried_stats["internal_duals"])==len(carried_stats["site_audit"])
		assert sum(value for key,value in carried_stats.items()
			if key not in ('diagnostic_examples','site_audit','internal_duals','subface_validation','grid_conflicts','directed_boundary','boundary_sides','pair_constraints','shared_boundary_audit','native_source_audit','degenerate_ray_sides'))==len(polygons)
		for polygon,label in zip(carried_polygons,carried_labels):
			if label is not None:
				assert polygon.distance(_site_geometry(label,1000.))<=1e-8
		repaired_polygons,repaired_labels,repair_stats=repair_test_cells(
			window,segments)
		assert len(repaired_polygons)==len(repaired_labels)
		assert repair_stats["gap_m2"]<1e-6
		assert repair_stats["overlap_m2"]<1e-6
		# Source-site geometry vetoes unsafe oblique replacements.
		if fixture in ("parallel","junction","crossing","oblique"):
			assert repair_stats["repaired_parent_faces"]=={"oblique":1}.get(fixture,0)
			assert repair_stats["still_unresolved"]=={
				"parallel":0,"junction":3,"crossing":0,"oblique":0}[fixture]
		repair_expected={
			"parallel":(9,9,0),"junction":(8,5,3),
			"crossing":(8,8,0),"oblique":(13,13,0),
			"fan":(6,5,1),"grid":(14,10,4),
			"near_parallel":(5,2,3)}
		assert (repair_stats["output_faces"],repair_stats["output_proven"],
			repair_stats["still_unresolved"])==repair_expected[fixture]
		for polygon,label in zip(repaired_polygons,repaired_labels):
			if label is not None:
				assert polygon.distance(_site_geometry(label,1000.))<=1e-8
		assert sum(value for key,value in stats.items()
			if key!='diagnostic_examples')==len(polygons)
		# Baseline of real native fixtures, not a blanket quality pass.
		# Open cases remain unresolved rather than receiving guessed sites.
		expected={
			"parallel":(9,9,0,0,0),
			"junction":(8,4,2,1,1),
			"crossing":(8,8,0,0,0),
			"oblique":(6,2,0,0,4),
			"fan":(6,5,0,1,0),
			"grid":(14,10,4,0,0),
			"near_parallel":(5,2,1,0,2)}
		actual=(len(polygons),stats["proven"],
			stats["conflicting_labels"],stats["insufficient_incidence"],
			stats["missing_boundary_labels"])
		assert actual==expected[fixture],(fixture,actual,expected[fixture])
		return {"fixture":fixture,"native_edges":len(edges),"clipped_fragments":len(segments),
			"cells":len(polygons),"native_endpoint_duals":len(endpoint_ids),
			"skeleton_comparison":{"full_fragments":len(full_lines),
				"skeleton_fragments":len(skeleton_lines),
				"removed_length_m":skeleton_removed,
				"extra_length_m":skeleton_outside,
				"kept_vs_skeleton_extra_m":skeleton_to_kept,
				"kept_vs_skeleton_missing_m":kept_to_skeleton,
				"excluded_native_edge_ids":excluded_ids,
				"skeleton_faces":len(skeleton_faces),
				"skeleton_gap_m2":skeleton_gap},**stats,"experimental_noded":new_stats,
			"experimental_carried":carried_stats,
			"experimental_repair":repair_stats}


def main():
	parser=argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--binary",type=Path,required=True)
	parser.add_argument("--diagnose",action="store_true",
		help="Include concrete unresolved face and missing-boundary geometry")
	args=parser.parse_args()
	for fixture in ("parallel","junction","crossing","oblique",
			"fan","grid","near_parallel"):
		print(json.dumps(verify_native_fixture(args.binary,fixture=fixture,
			diagnose=args.diagnose),sort_keys=True))


if __name__=="__main__":
	main()
