"""Conservative second-stage QA of reconstructed CGAL subfaces.

An internal ring is not automatically an independent Voronoi cell.
No generator assignment is made unless labelled boundary incidence
supports it. This module is diagnostic only.
"""
from shapely.ops import polygonize_full,unary_union

from scripts.cgal_internal_dual_audit import _lines
from scripts.cgal_topology_proof import reconstruct_test_cells


def inspect_subfaces(face,labelled_segments,*,tolerance=1e-7,
		return_cells=False):
	if face.is_empty or not face.is_valid or face.area<=0:
		raise ValueError("Invalid parent face")
	internal=[]
	for line,pair in labelled_segments:
		if not face.intersects(line):
			continue
		for fragment in _lines(line.intersection(face)):
			internal.append((fragment,pair))
	noded=unary_union([face.boundary,*(line for line,_ in internal)])
	rings,dangles,cuts,invalid=polygonize_full(noded)
	subfaces=[p for p in rings.geoms
		if p.area>0 and face.covers(p.representative_point())]
	excluded=[p for p in rings.geoms
		if p.area>0 and not face.covers(p.representative_point())]
	excluded_details=[{
		"area_m2":p.area,"bounds":list(p.bounds),
		"inside_parent_area_m2":p.intersection(face).area,
		"holes":len(p.interiors),"covers_parent":p.covers(face)}
		for p in excluded]
	if not subfaces:
		raise ValueError("No subfaces")
	covered=unary_union(subfaces)
	gap=face.difference(covered).area
	outside=covered.difference(face).area
	overlap=sum(p.area for p in subfaces)-covered.area
	area_tol=max(tolerance**2,face.area*1e-10)
	geometry_ok=(gap<=area_tol and outside<=area_tol and overlap<=area_tol
		and invalid.is_empty)
	# Independent boundary proof only: do not replace the subfaces with
	# another polygonization whose face indexing may differ.
	proven=0
	ambiguous=0
	accepted_cells=[]
	reasons={}
	comparison={"partition_match":False,"reference_subfaces":None,
		"only_first_area_m2":None,"only_reference_area_m2":None,
		"max_best_symmetric_difference_m2":None}
	if geometry_ok and internal:
		# Independently prove labels and match the very same subface set.
		all_proof_polygons,all_proof_labels,proof_stats=reconstruct_test_cells(
			face,internal,tolerance=tolerance,carried_provenance=True)
		# The topology proof may polygonize a ring OUTSIDE the parent.
		# Compare only faces belonging to this parent, preserving labels.
		accepted=[(p,label) for p,label in zip(
			all_proof_polygons,all_proof_labels)
			if p.area>0 and face.covers(p.representative_point())]
		proof_polygons=[p for p,_ in accepted]
		proof_labels=[label for _,label in accepted]
		differences=[min((p.symmetric_difference(q).area
			for q in proof_polygons),default=p.area) for p in subfaces]
		match=(len(proof_polygons)==len(subfaces)
			and all(any(p.equals(q) for q in proof_polygons) for p in subfaces))
		first_union=unary_union(subfaces)
		ref_union=unary_union(proof_polygons)
		comparison={"partition_match":match,
			"reference_subfaces":len(proof_polygons),
			"reference_total_polygons":len(all_proof_polygons),
			"reference_excluded":len(all_proof_polygons)-len(proof_polygons),
			"only_first_area_m2":first_union.difference(ref_union).area,
			"only_reference_area_m2":ref_union.difference(first_union).area,
			"max_best_symmetric_difference_m2":max(differences,default=0.)}
		if match:
			accepted_cells=[(p,next(label for q,label in accepted if p.equals(q)))
				for p in subfaces]
			proven=sum(label is not None for label in proof_labels)
			ambiguous=len(proof_labels)-proven
			reasons={key:value for key,value in proof_stats.items()
				if isinstance(value,int)}
		else:
			geometry_ok=False
	if not geometry_ok:
		proven=0
		ambiguous=len(subfaces)
		reasons={}
	report={"raw_polygonized_rings":len(rings.geoms),
		"filtered_out_rings":len(rings.geoms)-len(subfaces),
		"excluded_ring_details":excluded_details,
		"independent_comparison":comparison,
		"subfaces":len(subfaces),"area_m2":face.area,
		"gap_m2":gap,"outside_m2":outside,"overlap_m2":overlap,
		"geometry_valid":geometry_ok,
		"proven_subfaces":proven,"unresolved_subfaces":ambiguous,
		"unresolved_reasons":reasons,
		"cuts":len(cuts.geoms),"dangles":len(dangles.geoms),
		"invalid_rings":len(invalid.geoms)}
	if return_cells:
		# No geometries are released if the full partition failed QA.
		return (accepted_cells if geometry_ok else []),report
	return report
