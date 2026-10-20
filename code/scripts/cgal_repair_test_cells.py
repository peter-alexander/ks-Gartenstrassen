"""Fail-closed experimental CGAL reconstruction repair for small fixtures.

Unchanged proven faces are kept. An unresolved face is replaced only when
all independently reconstructed subfaces have a labelled native generator
and jointly cover the original face without overlap. No Vienna builder use.
"""
from shapely.ops import unary_union

from scripts.cgal_topology_proof import reconstruct_test_cells
from scripts.cgal_subface_validation import inspect_subfaces
from scripts.cgal_unresolved_site_audit import _metric_site
from scripts.cgal_generator_mismatch_audit import incompatible_candidates


def repair_test_cells(window,labelled_segments,*,tolerance=1e-7):
	polygons,labels,baseline=reconstruct_test_cells(
		window,labelled_segments,tolerance=tolerance,carried_provenance=True)
	result_polygons=[]
	result_labels=[]
	repaired=0
	rejected=0
	replaced_faces=[]
	generator_mismatches=[]
	for face_id,(polygon,label) in enumerate(zip(polygons,labels)):
		if label is not None:
			result_polygons.append(polygon)
			result_labels.append(label)
			continue
		candidates,report=inspect_subfaces(polygon,labelled_segments,
			tolerance=tolerance,return_cells=True)
		if (report["geometry_valid"] and len(candidates)>1
				and all(owner is not None for _,owner in candidates)
				and all(subface.intersects(_metric_site(owner,1000.))
					for subface,owner in candidates)
				and report["proven_subfaces"]==len(candidates)):
			repaired+=1
			replaced_faces.append({"face_index":face_id,
				"new_faces":len(candidates)})
			for face,owner in candidates:
				result_polygons.append(face)
				result_labels.append(owner)
		else:
			if candidates:
				for detail in incompatible_candidates(candidates,labelled_segments):
					detail["parent_face_index"]=face_id
					generator_mismatches.append(detail)
			rejected+=1
			result_polygons.append(polygon)
			result_labels.append(None)
	original_union=unary_union(polygons)
	repaired_union=unary_union(result_polygons)
	limit=max(tolerance*tolerance,window.area*1e-10)
	gap=original_union.difference(repaired_union).area
	extra=repaired_union.difference(original_union).area
	overlap=sum(p.area for p in result_polygons)-repaired_union.area
	if gap>limit or extra>limit or overlap>limit:
		raise ValueError("Repaired partition failed area conservation")
	return result_polygons,result_labels,{
		"original_faces":len(polygons),"output_faces":len(result_polygons),
		"original_proven":sum(v is not None for v in labels),
		"output_proven":sum(v is not None for v in result_labels),
		"repaired_parent_faces":repaired,
		"unresolved_parent_faces":rejected,
		"still_unresolved":sum(v is None for v in result_labels),
		"gap_m2":gap,"extra_m2":extra,"overlap_m2":overlap,
		"replacements":replaced_faces,
		"generator_mismatches":generator_mismatches}
