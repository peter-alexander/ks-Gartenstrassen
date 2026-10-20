"""Conservative second-stage QA of reconstructed CGAL subfaces.

An internal ring is not automatically an independent Voronoi cell.
No generator assignment is made unless labelled boundary incidence
supports it. This module is diagnostic only.
"""
from shapely.ops import polygonize_full,unary_union

from scripts.cgal_internal_dual_audit import _lines
from scripts.cgal_topology_proof import reconstruct_test_cells


def inspect_subfaces(face,labelled_segments,*,tolerance=1e-7):
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
	reasons={}
	if geometry_ok and internal:
		# Independently prove labels and match the very same subface set.
		proof_polygons,proof_labels,proof_stats=reconstruct_test_cells(
			face,internal,tolerance=tolerance,carried_provenance=True)
		match=all(any(p.equals(q) for q in proof_polygons) for p in subfaces)
		if match and len(proof_polygons)==len(subfaces):
			proven=sum(label is not None for label in proof_labels)
			ambiguous=len(proof_labels)-proven
			reasons={key:value for key,value in proof_stats.items()
				if isinstance(value,int)}
		else:
			geometry_ok=False
	else:
		ambiguous=len(subfaces)
	return {"subfaces":len(subfaces),"area_m2":face.area,
		"gap_m2":gap,"outside_m2":outside,"overlap_m2":overlap,
		"geometry_valid":geometry_ok,
		"proven_subfaces":proven,"unresolved_subfaces":ambiguous,
		"unresolved_reasons":reasons,
		"cuts":len(cuts.geoms),"dangles":len(dangles.geoms),
		"invalid_rings":len(invalid.geoms)}
