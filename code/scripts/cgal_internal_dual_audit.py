"""Read-only audit of CGAL dual edges within unresolved reconstructed faces.

Only a small native-fixture diagnostic. Distinguishes cut edges (from
polygonize_full) from complete rings. Does not infer generator ownership.
"""
from shapely.geometry import LineString
from shapely.ops import polygonize_full, unary_union


def _lines(geometry):
	if isinstance(geometry,LineString):
		if geometry.length>0:
			yield geometry
	elif hasattr(geometry,"geoms"):
		for part in geometry.geoms:
			yield from _lines(part)


def audit_internal_duals(polygons,labels,labelled_segments,*,limit=12):
	if len(polygons)!=len(labels) or limit<1:
		raise ValueError("Invalid CGAL dual audit arguments")
	result=[]
	for face_id,(face,label) in enumerate(zip(polygons,labels)):
		if label is not None:
			continue
		internal=[]
		touching=0
		contained=0
		pair_set=set()
		for line,pair in labelled_segments:
			if not face.intersects(line):
				continue
			if face.covers(line):
				contained+=1
			else:
				touching+=1
			clipped=line.intersection(face)
			for fragment in _lines(clipped):
				if fragment.length>0:
					internal.append(fragment)
					pair_set.add(frozenset(pair))
		# Internal geometry alone cannot create a ring when borders are
		# required; include the reconstructed face boundary in this QA.
		noded=unary_union([face.boundary,*internal])
		rings,dangles,cuts,invalid=polygonize_full(noded)
		cut_parts=list(_lines(cuts))
		dangle_parts=list(_lines(dangles))
		result.append({
			"face_index":face_id,
			"area_m2":face.area,
			"source_segments_fully_contained":contained,
			"source_segments_touching_boundary":touching,
			"clipped_dual_fragments":len(internal),
			"generator_pairs":len(pair_set),
			"polygonized_subfaces":len(rings.geoms),
			"cuts":len(cut_parts),
			"cuts_length_m":sum(item.length for item in cut_parts),
			"dangles":len(dangle_parts),
			"dangles_length_m":sum(item.length for item in dangle_parts),
			"invalid_rings":len(invalid.geoms),
			"cut_examples_wkt":[item.wkt for item in cut_parts[:limit]],
			"dangle_examples_wkt":[item.wkt for item in dangle_parts[:limit]]})
	return result
