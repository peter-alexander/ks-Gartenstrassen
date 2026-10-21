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
from scripts.cgal_unresolved_native_source_census import audit_unresolved_native_sources
from scripts.cgal_unresolved_endpoint_conflicts import audit_unresolved_endpoint_conflicts
from scripts.cgal_unresolved_side_conflict_crosscheck import audit_unresolved_side_conflict_crosscheck
from scripts.cgal_coincident_ray_distance_witness import audit_coincident_ray_distance_witness
from scripts.cgal_unresolved_area_distance_bounds import audit_unresolved_area_distance_bounds
from scripts.cgal_unknown_tile_counterexamples import audit_unknown_tile_counterexamples
from scripts.cgal_endpoint_blocker_dominance import audit_endpoint_blocker_dominance
from scripts.cgal_segment_blocker_witnesses import audit_segment_blocker_witnesses
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
from scripts.cgal_endpoint_dual_candidates import audit_endpoint_dual_candidates
from scripts.cgal_endpoint_neighbor_audit import audit_endpoint_neighbor_constraints
from scripts.cgal_directed_side_calibration import audit_directed_side_calibration
from scripts.cgal_actual_shared_ray_sides import audit_actual_shared_ray_sides
from scripts.cgal_primal_side_hypothesis import audit_primal_side_hypothesis
from scripts.cgal_endpoint_ray_local_sides import audit_endpoint_ray_local_sides
from scripts.cgal_coincident_endpoint_group import audit_coincident_endpoint_group
from scripts.cgal_group_topology_consistency import audit_group_topological_consistency
from scripts.cgal_group_primal_indices import audit_group_primal_indices
from scripts.cgal_primal_index_calibration import audit_primal_index_calibration
from scripts.cgal_signature_coverage import audit_signature_coverage
from scripts.cgal_endpoint_primal_star import audit_endpoint_primal_star
from scripts.cgal_endpoint_third_edge import audit_endpoint_third_edges
from scripts.cgal_primal_face_identity import parse_primal_face_pairs,audit_group_primal_faces
from scripts.cgal_primal_face_vertices import parse_primal_face_vertices
from scripts.cgal_primal_face_neighbors import parse_primal_face_neighbors
from scripts.cgal_primal_mirror_slots import audit_primal_mirror_slots
from scripts.cgal_endpoint_mirror_chain import audit_endpoint_mirror_chain
from scripts.cgal_endpoint_vertex_slots import audit_endpoint_vertex_slots
from scripts.cgal_endpoint_opposite_slots import audit_endpoint_primal_opposite_slots
from scripts.cgal_endpoint_face_circulation import audit_endpoint_face_circulation
from scripts.cgal_endpoint_cycle_coverage import audit_endpoint_cycle_coverage
from scripts.cgal_endpoint_cycle_site_pairs import audit_endpoint_cycle_site_pairs
from scripts.cgal_cycle_edge_site_match import audit_cycle_edge_site_match
from scripts.cgal_cycle_dual_incidence import audit_cycle_dual_incidence
from scripts.cgal_endpoint_dual_side_guard import audit_endpoint_dual_side_evidence
from scripts.cgal_endpoint_cw_ccw_audit import audit_endpoint_cw_ccw_pairs
from scripts.cgal_endpoint_cw_ccw_cycle_alignment import audit_endpoint_cw_ccw_cycle_alignment
from scripts.cgal_endpoint_dual_ray_direction import audit_endpoint_dual_ray_directions
from scripts.cgal_endpoint_dual_primitives import audit_endpoint_dual_primitives
from scripts.cgal_endpoint_zero_third_dual import audit_endpoint_zero_length_third_dual
from scripts.cgal_shared_face_slots import audit_shared_face_slots
from scripts.cgal_three_edge_face_adjacency import audit_three_edge_face_adjacency
from scripts.cgal_endpoint_face_chain import audit_endpoint_face_chain
from scripts.cgal_endpoint_face_star_incidence import audit_endpoint_face_star_incidence


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
			str(temp/"topology.txt"),"--face-incidence",
			str(temp/"incidence.txt"),"--primal-face-pairs",str(temp/"primal_faces.txt"),"--primal-face-vertices",str(temp/"primal_vertices.txt"),"--primal-face-neighbors",str(temp/"primal_neighbors.txt"),"--ray-directions",
			str(temp/"directions.txt"),"--skeleton-edge-ids",
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
		primal_face_pairs=parse_primal_face_pairs(
			(temp/"primal_faces.txt").read_text(encoding="utf-8").splitlines(),len(edges))
		primal_face_vertices=parse_primal_face_vertices(
			(temp/"primal_vertices.txt").read_text(encoding="utf-8").splitlines(),
			len(edges),primal_face_pairs)
		assert len(primal_face_vertices)==len(edges)
		primal_face_neighbors=parse_primal_face_neighbors(
			(temp/"primal_neighbors.txt").read_text(encoding="utf-8").splitlines(),
			len(edges),primal_face_pairs)
		assert not primal_face_neighbors["cyclic_order_proven"]
		assert not primal_face_neighbors["ownership_proven"]

		endpoint_ids=[]
		for index,record in enumerate(topology):
			fields=record.split(maxsplit=4)
			assert fields[:2]==["T",str(index)]
			assert fields[2] in ("0","1") and fields[3]=="CW"
			assert " | CCW " in fields[4]
			if fields[2]=="1":
				endpoint_ids.append(index)
		assert native["endpoint_duals"]==len(endpoint_ids)
		directed_lines=(temp/"directions.txt").read_text(encoding="utf-8").splitlines()
		assert sum(line.startswith("E ") for line in directed_lines)==len(edges)
		rays={}
		current=None
		for line in directed_lines:
			parts=line.split()
			if parts[0]=="E":
				current=int(parts[1])
				assert 0<=current<len(edges)
			elif parts[0]=="R":
				assert current is not None and len(parts)==5
				rays.setdefault(current,[]).append([float(x)/1000.
					for x in parts[1:]])
		assert all(len(rays.get(edge_id,[]))==1 for edge_id in (18,22,25,26)
			) if fixture=="grid" else True
		incidence=(temp/"incidence.txt").read_text(encoding="utf-8").splitlines()
		assert len(incidence)==len(edges)
		face_incidence={}
		for index,record in enumerate(incidence):
			fields=record.split(maxsplit=6)
			assert fields[:2]==["F",str(index)]
			assert fields[2] in ("0","1","2") and fields[3] in ("0","1","2")
			assert fields[4] in ("0","1") and fields[5] in ("0","1")
			assert fields[6].startswith("OPP ") and " | NEIGH " in fields[6]
			face_incidence[index]={"local_index":int(fields[2]),
				"neighbor_index":int(fields[3]),
				"primary_finite":fields[4]=="1",
				"neighbor_finite":fields[5]=="1",
				"opposite_sites":fields[6]}
		primal_mirror_slots=audit_primal_mirror_slots(
			primal_face_pairs,face_incidence,primal_face_neighbors)
		assert len(primal_mirror_slots)==len(edges)
		assert all(not row["ownership_proven"] and not row["cyclic_order_proven"]
			for row in primal_mirror_slots)
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
		carried_stats["endpoint_dual_experiment"]=audit_endpoint_dual_candidates(
			carried_polygons,carried_labels,segments,window)
		carried_stats["endpoint_neighbor_audit"]=audit_endpoint_neighbor_constraints(
			carried_polygons,carried_labels,segments,window)
		assert len(carried_stats["endpoint_dual_experiment"])==len(carried_polygons)
		assert all(item["status"]!="candidate_only_not_proven"
			or carried_labels[item["face_index"]] is None
			for item in carried_stats["endpoint_dual_experiment"])
		assert len(carried_polygons)==len(polygons)
		carried_stats["side_calibration"]=audit_directed_side_calibration(
			carried_polygons,carried_labels,edges,rays)
		carried_stats["actual_shared_ray_sides"]=audit_actual_shared_ray_sides(
			carried_polygons,carried_labels,edges,rays,window)
		carried_stats["primal_side_comparison"]=[
			{**row,**face_incidence[row["edge_id"]]}
			for row in carried_stats["actual_shared_ray_sides"]]
		carried_stats["side_hypothesis"]=audit_primal_side_hypothesis(
			carried_stats["primal_side_comparison"])
		carried_stats["side_hypothesis_summary"]={
			"supported":sum(r["status"]=="supported" for r in carried_stats["side_hypothesis"]),
			"counterexamples":sum(r["status"]=="counterexample" for r in carried_stats["side_hypothesis"]),
			"untested":sum(r["status"]=="untested" for r in carried_stats["side_hypothesis"])}
		if fixture=="grid":
			assert len(carried_stats["primal_side_comparison"])==4
			assert {row["edge_id"] for row in
				carried_stats["primal_side_comparison"]}=={1,4,16,19}
		carried_stats["site_audit"]=inspect_unresolved_faces(
			carried_polygons,carried_labels,edges)
		carried_stats["unresolved_native_sources"]=audit_unresolved_native_sources(
			carried_polygons,carried_labels,edges,window)
		assert {row["face_index"] for row in carried_stats["unresolved_native_sources"]}=={
			row["face_index"] for row in carried_stats["site_audit"]}
		assert all(row["status"]=="native_boundary_sources_only_no_owner"
			and not row["ownership_proven"] for row in carried_stats["unresolved_native_sources"])
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
				finding["native_directed_rays"]=[
					{"edge_id":edge_id,"ray_source":ray[:2],
						"ray_second_point":ray[2:],
						"direction":[ray[2]-ray[0],ray[3]-ray[1]]}
					for edge_id in finding["native_edge_ids"]
					for ray in rays.get(edge_id,[])]
				finding["primal_face_incidence"]=[
					{"edge_id":edge_id,**face_incidence[edge_id]}
					for edge_id in finding["native_edge_ids"]]
				finding["orientation_hypothesis"]=[
					{"edge_id":edge_id,
						"predicted_first_site_side":(
							"left" if face_incidence[edge_id]["primary_finite"]
								and not face_incidence[edge_id]["neighbor_finite"]
							else "right" if not face_incidence[edge_id]["primary_finite"]
								and face_incidence[edge_id]["neighbor_finite"]
							else "unverified"),
						"proof_status":"hypothesis_only"}
					for edge_id in finding["native_edge_ids"]]
				assert all(row["proof_status"]=="hypothesis_only"
					for row in finding["orientation_hypothesis"])
			carried_stats["endpoint_ray_local_sides"]=audit_endpoint_ray_local_sides(
				carried_polygons,carried_labels,
				carried_stats["endpoint_dual_experiment"],
				carried_stats["degenerate_ray_sides"],
				edges,rays,face_incidence,window)
			assert len(carried_stats["endpoint_ray_local_sides"])==2
			assert all(not row["ownership_proven"]
				for row in carried_stats["endpoint_ray_local_sides"])
			carried_stats["coincident_endpoint_groups"]=[
				audit_coincident_endpoint_group(row["native_edge_ids"],
					edges,rays,face_incidence)
				for row in carried_stats["degenerate_ray_sides"]]
			assert len(carried_stats["coincident_endpoint_groups"])==2
			assert all(row["status"]=="grouped_diagnostic_only"
				and not row["ownership_proven"]
				for row in carried_stats["coincident_endpoint_groups"])
			carried_stats["group_topological_consistency"]=(
				audit_group_topological_consistency(
					carried_stats["coincident_endpoint_groups"],
					carried_stats["endpoint_ray_local_sides"],
					carried_stats["endpoint_neighbor_audit"]))
			assert len(carried_stats["group_topological_consistency"])==2
			assert all(row["status"]=="regular_neighbors_consistent_endpoint_ambiguous"
				and row["known_neighbor_constraints"]==4
				and row["known_neighbor_mismatches"]==0
				and row["endpoint_edge_fragments"]==6
				and row["endpoint_candidate_conflicts"]==2
				and not row["ownership_proven"]
				for row in carried_stats["group_topological_consistency"])
			carried_stats["group_primal_indices"]=audit_group_primal_indices(
				carried_stats["coincident_endpoint_groups"],face_incidence)
			assert len(carried_stats["group_primal_indices"])==2
			assert all(row["status"]=="native_incidence_recorded_not_ownership"
				and not row["ownership_proven"]
				for row in carried_stats["group_primal_indices"])
			carried_stats["primal_index_calibration"]=audit_primal_index_calibration(
				carried_stats["group_primal_indices"],
				carried_stats["primal_side_comparison"])
			assert len(carried_stats["primal_index_calibration"])==2
			assert all(row["status"]=="comparison_only_no_ownership_inference"
				and not row["ownership_proven"] and len(row["native_edges"])==2
				for row in carried_stats["primal_index_calibration"])
			carried_stats["endpoint_primal_star"]=audit_endpoint_primal_star(
				carried_stats["coincident_endpoint_groups"],edges,face_incidence)
			assert len(carried_stats["endpoint_primal_star"])==2
			assert all(row["status"]=="native_incident_star_unordered_only"
				and not row["cyclic_order_proven"] and not row["ownership_proven"]
				for row in carried_stats["endpoint_primal_star"])
			carried_stats["endpoint_third_edges"]=audit_endpoint_third_edges(
				carried_stats["coincident_endpoint_groups"],
				carried_stats["endpoint_primal_star"])
			assert len(carried_stats["endpoint_third_edges"])==2
			assert {row["third_edge_id"] for row in carried_stats["endpoint_third_edges"]}=={28,30}
			assert all(row["status"]=="third_native_edge_observed_no_rotation_proof"
				and not row["cyclic_order_proven"] and not row["ownership_proven"]
				for row in carried_stats["endpoint_third_edges"])
			carried_stats["primal_face_identity"]=audit_group_primal_faces(
				carried_stats["coincident_endpoint_groups"],primal_face_pairs)
			assert len(carried_stats["primal_face_identity"])==2
			assert all(row["status"]=="native_face_identity_observed_only"
				and not row["cyclic_order_proven"] and not row["ownership_proven"]
				for row in carried_stats["primal_face_identity"])
			carried_stats["three_edge_face_adjacency"]=audit_three_edge_face_adjacency(
				carried_stats["endpoint_third_edges"],primal_face_pairs)
			assert len(carried_stats["three_edge_face_adjacency"])==2
			assert all(row["status"]=="native_three_edge_adjacency_observed_only"
				and not row["cyclic_order_proven"] and not row["ownership_proven"]
				for row in carried_stats["three_edge_face_adjacency"])
			carried_stats["endpoint_face_chain"]=audit_endpoint_face_chain(
				carried_stats["three_edge_face_adjacency"])
			assert len(carried_stats["endpoint_face_chain"])==2
			assert all(row["status"]=="native_face_chain_confirmed_not_ownership"
				and not row["cyclic_order_proven"] and not row["ownership_proven"]
				for row in carried_stats["endpoint_face_chain"])
			carried_stats["endpoint_face_star_incidence"]=audit_endpoint_face_star_incidence(
				carried_stats["endpoint_primal_star"],
				carried_stats["endpoint_face_chain"],primal_face_pairs)
			assert len(carried_stats["endpoint_face_star_incidence"])==2
			assert all(row["status"]=="native_face_star_incidence_checked_only"
				and not row["cyclic_order_proven"] and not row["ownership_proven"]
				for row in carried_stats["endpoint_face_star_incidence"])
			carried_stats["shared_face_slots"]=audit_shared_face_slots(
				primal_face_vertices,carried_stats["endpoint_face_chain"])
			assert len(carried_stats["shared_face_slots"])==2
			assert all(row["status"]=="shared_native_triangle_slots_identical_only"
				and not row["cyclic_order_proven"] and not row["ownership_proven"]
				for row in carried_stats["shared_face_slots"])
			carried_stats["endpoint_mirror_chain"]=audit_endpoint_mirror_chain(
				carried_stats["endpoint_face_chain"],
				primal_face_pairs,face_incidence,primal_face_neighbors)
			assert len(carried_stats["endpoint_mirror_chain"])==2
			assert all(row["status"]=="mirror_chain_consistent_no_rotation_proof"
				and not row["cyclic_order_proven"] and not row["ownership_proven"]
				for row in carried_stats["endpoint_mirror_chain"])
			carried_stats["endpoint_vertex_slots"]=audit_endpoint_vertex_slots(
				carried_stats["endpoint_primal_star"],
				primal_face_pairs,primal_face_vertices)
			assert len(carried_stats["endpoint_vertex_slots"])==2
			assert all(row["status"]=="native_point_vertex_slots_observed_only"
				and not row["cyclic_order_proven"] and not row["ownership_proven"]
				for row in carried_stats["endpoint_vertex_slots"])
			carried_stats["endpoint_opposite_slots"]=audit_endpoint_primal_opposite_slots(
				carried_stats["endpoint_primal_star"],
				carried_stats["endpoint_vertex_slots"],
				primal_face_pairs,face_incidence)
			assert len(carried_stats["endpoint_opposite_slots"])==2
			assert all(row["status"]=="native_point_on_primal_edge_checked_only"
				and not row["cyclic_order_proven"] and not row["ownership_proven"]
				for row in carried_stats["endpoint_opposite_slots"])
			carried_stats["endpoint_face_circulation"]=audit_endpoint_face_circulation(
				carried_stats["endpoint_primal_star"],
				carried_stats["endpoint_vertex_slots"],primal_face_neighbors)
			assert len(carried_stats["endpoint_face_circulation"])==2
			assert all(not row["ownership_proven"]
				and row["status"] in ("complete_native_face_cycle_only",
					"blocked_incomplete_or_ambiguous_face_circulation")
				for row in carried_stats["endpoint_face_circulation"])
			carried_stats["endpoint_cycle_coverage"]=audit_endpoint_cycle_coverage(
				carried_stats["endpoint_primal_star"],
				carried_stats["endpoint_face_circulation"])
			assert all(row["status"]=="native_four_face_cycle_observed_no_ownership"
				and row["cyclic_order_proven"] and not row["ownership_proven"]
				for row in carried_stats["endpoint_cycle_coverage"])
			carried_stats["endpoint_cycle_site_pairs"]=audit_endpoint_cycle_site_pairs(
				carried_stats["endpoint_primal_star"],
				carried_stats["endpoint_face_circulation"],
				primal_face_pairs,primal_face_vertices)
			assert len(carried_stats["endpoint_cycle_site_pairs"])==2
			assert all(row["status"]=="native_cycle_shared_sites_verified_only"
				and row["cyclic_order_proven"] and not row["ownership_proven"]
				for row in carried_stats["endpoint_cycle_site_pairs"])
			carried_stats["cycle_edge_site_match"]=audit_cycle_edge_site_match(
				carried_stats["endpoint_primal_star"],
				carried_stats["endpoint_cycle_site_pairs"])
			assert len(carried_stats["cycle_edge_site_match"])==2
			assert all(row["status"]=="native_cycle_edge_sites_identical_only"
				and row["cyclic_order_proven"] and not row["ownership_proven"]
				for row in carried_stats["cycle_edge_site_match"])
			carried_stats["cycle_dual_incidence"]=audit_cycle_dual_incidence(
				carried_stats["endpoint_primal_star"],
				carried_stats["endpoint_cycle_site_pairs"],
				primal_face_pairs,face_incidence,set(endpoint_ids))
			assert len(carried_stats["cycle_dual_incidence"])==2
			assert all(row["status"]=="native_cycle_dual_incidence_only"
				and not row["voronoi_side_proven"] and not row["ownership_proven"]
				for row in carried_stats["cycle_dual_incidence"]), {
				"report":carried_stats["cycle_dual_incidence"],
				"cycle_sites":carried_stats["endpoint_cycle_site_pairs"],
				"primal_pairs":primal_face_pairs,
				"star":carried_stats["endpoint_primal_star"]}
			carried_stats["endpoint_dual_side_guard"]=audit_endpoint_dual_side_evidence(
				carried_stats["cycle_dual_incidence"],
				carried_stats["primal_side_comparison"])
			assert len(carried_stats["endpoint_dual_side_guard"])==2
			assert all(row["status"]=="degenerate_duals_require_independent_side_proof"
				and not row["voronoi_side_proven"] and not row["ownership_proven"]
				for row in carried_stats["endpoint_dual_side_guard"])
			carried_stats["endpoint_cw_ccw_pairs"]=audit_endpoint_cw_ccw_pairs(
				carried_stats["endpoint_primal_star"],
				carried_stats["cycle_dual_incidence"],topology,edges)
			assert len(carried_stats["endpoint_cw_ccw_pairs"])==2
			assert all(row["status"]=="native_endpoint_cw_ccw_pair_recorded_only"
				and not row["voronoi_side_proven"] and not row["ownership_proven"]
				for row in carried_stats["endpoint_cw_ccw_pairs"])
			carried_stats["endpoint_cw_ccw_cycle_alignment"]=audit_endpoint_cw_ccw_cycle_alignment(
				carried_stats["cycle_dual_incidence"],
				carried_stats["endpoint_cw_ccw_pairs"])
			assert len(carried_stats["endpoint_cw_ccw_cycle_alignment"])==2
			assert all(row["status"]=="native_cw_ccw_cycle_alignment_only"
				and not row["voronoi_side_proven"] and not row["ownership_proven"]
				for row in carried_stats["endpoint_cw_ccw_cycle_alignment"])
			carried_stats["endpoint_dual_ray_directions"]=audit_endpoint_dual_ray_directions(
				carried_stats["endpoint_cw_ccw_cycle_alignment"],rays)
			assert len(carried_stats["endpoint_dual_ray_directions"])==2
			assert all(row["status"] in (
				"native_endpoint_ray_directions_recorded_only",
				"blocked_endpoint_ray_direction_evidence")
				and not row["voronoi_side_proven"] and not row["ownership_proven"]
				for row in carried_stats["endpoint_dual_ray_directions"])
			assert {edge_id for row in carried_stats["endpoint_dual_ray_directions"]
				for edge_id in row["missing_ray_edge_ids"]}=={28,30}, (
				carried_stats["endpoint_dual_ray_directions"])
			carried_stats["endpoint_dual_primitives"]=audit_endpoint_dual_primitives(
				carried_stats["endpoint_primal_star"],
				carried_stats["endpoint_dual_ray_directions"],edges)
			assert len(carried_stats["endpoint_dual_primitives"])==2
			assert all(row["status"]=="native_endpoint_dual_primitives_recorded_only"
				and not row["voronoi_side_proven"] and not row["ownership_proven"]
				for row in carried_stats["endpoint_dual_primitives"])
			carried_stats["endpoint_zero_third_dual"]=audit_endpoint_zero_length_third_dual(
				carried_stats["endpoint_primal_star"],
				carried_stats["endpoint_dual_primitives"])
			assert len(carried_stats["endpoint_zero_third_dual"])==2
			assert {row["third_edge_id"] for row in carried_stats["endpoint_zero_third_dual"]}=={28,30}
			assert all(row["status"]=="native_coincident_rays_zero_third_dual_only"
				and not row["voronoi_side_proven"] and not row["ownership_proven"]
				for row in carried_stats["endpoint_zero_third_dual"])
			carried_stats["unresolved_endpoint_conflicts"]=audit_unresolved_endpoint_conflicts(
				carried_stats["endpoint_dual_experiment"],
				carried_stats["unresolved_native_sources"],
				carried_stats["endpoint_primal_star"],
				carried_stats["endpoint_zero_third_dual"])
			assert {row["face_index"] for row in carried_stats["unresolved_endpoint_conflicts"]}=={1,2,6,7}
			assert all(row["status"]=="coincident_endpoint_conflict_isolated_not_resolved"
				and not row["ownership_proven"]
				for row in carried_stats["unresolved_endpoint_conflicts"])
			carried_stats["unresolved_side_conflict_crosscheck"]=audit_unresolved_side_conflict_crosscheck(
				carried_stats["endpoint_ray_local_sides"],
				carried_stats["unresolved_endpoint_conflicts"])
			assert len(carried_stats["unresolved_side_conflict_crosscheck"])==2
			assert all(row["status"]=="geometric_sides_and_conflicts_consistent_only"
				and not row["ownership_proven"]
				for row in carried_stats["unresolved_side_conflict_crosscheck"])
			carried_stats["coincident_ray_distance_witness"]=audit_coincident_ray_distance_witness(
				carried_polygons,carried_stats["endpoint_ray_local_sides"],rays)
			assert len(carried_stats["coincident_ray_distance_witness"])==2
			assert all(row["status"]=="finite_distance_samples_recorded_only"
				and not row["ownership_proven"]
				for row in carried_stats["coincident_ray_distance_witness"])
			carried_stats["unresolved_area_distance_bounds"]=audit_unresolved_area_distance_bounds(
				carried_polygons,carried_labels,edges,
				carried_stats["endpoint_dual_experiment"])
			assert {row["face_index"] for row in carried_stats["unresolved_area_distance_bounds"]}=={1,2,6,7}
			assert all(row["status"] in (
				"full_area_distance_bound_verified_only",
				"partial_area_distance_bound_unknown")
				and not row["ownership_proven"]
				for row in carried_stats["unresolved_area_distance_bounds"])
			carried_stats["unknown_tile_counterexamples"]=audit_unknown_tile_counterexamples(
				carried_polygons,carried_labels,edges,
				carried_stats["endpoint_dual_experiment"],
				carried_stats["unresolved_area_distance_bounds"])
			assert {row["face_index"] for row in carried_stats["unknown_tile_counterexamples"]}=={1,2,6,7}
			assert all(not row["ownership_proven"]
				for row in carried_stats["unknown_tile_counterexamples"])
			carried_stats["endpoint_blocker_dominance"]=audit_endpoint_blocker_dominance(
				carried_stats["endpoint_dual_experiment"],
				carried_stats["unresolved_area_distance_bounds"])
			assert {row["face_index"] for row in carried_stats["endpoint_blocker_dominance"]}=={1,2,6,7}
			assert all(not row["ownership_proven"]
				for row in carried_stats["endpoint_blocker_dominance"])
			carried_stats["segment_blocker_witnesses"]=audit_segment_blocker_witnesses(
				carried_polygons,carried_labels,
				carried_stats["endpoint_dual_experiment"],
				carried_stats["unresolved_area_distance_bounds"])
			assert {row["face_index"] for row in carried_stats["segment_blocker_witnesses"]}=={1,2,6,7}
			assert all(not row["ownership_proven"]
				for row in carried_stats["segment_blocker_witnesses"])
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
			if key not in ('diagnostic_examples','site_audit','unresolved_native_sources','unresolved_endpoint_conflicts','unresolved_side_conflict_crosscheck','coincident_ray_distance_witness','unresolved_area_distance_bounds','unknown_tile_counterexamples','endpoint_blocker_dominance','segment_blocker_witnesses','internal_duals','subface_validation','grid_conflicts','directed_boundary','boundary_sides','pair_constraints','shared_boundary_audit','native_source_audit','degenerate_ray_sides','endpoint_ray_local_sides','coincident_endpoint_groups','group_topological_consistency','group_primal_indices','primal_index_calibration','endpoint_primal_star','endpoint_third_edges','primal_face_identity','three_edge_face_adjacency','endpoint_face_chain','endpoint_face_star_incidence','shared_face_slots','endpoint_mirror_chain','endpoint_vertex_slots','endpoint_opposite_slots','endpoint_face_circulation','endpoint_cycle_coverage','endpoint_cycle_site_pairs','cycle_edge_site_match','cycle_dual_incidence','endpoint_dual_side_guard','endpoint_cw_ccw_pairs','endpoint_cw_ccw_cycle_alignment','endpoint_dual_ray_directions','endpoint_dual_primitives','endpoint_zero_third_dual','endpoint_dual_experiment','endpoint_neighbor_audit','side_calibration','actual_shared_ray_sides','primal_side_comparison','side_hypothesis','side_hypothesis_summary'))==len(polygons)
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
	results=[]
	for fixture in ("parallel","junction","crossing","oblique",
			"fan","grid","near_parallel"):
		result=verify_native_fixture(args.binary,fixture=fixture,
			diagnose=args.diagnose)
		results.append(result)
		print(json.dumps(result,sort_keys=True))
	print(json.dumps({"signature_coverage":audit_signature_coverage(results)},
		sort_keys=True))


if __name__=="__main__":
	main()
