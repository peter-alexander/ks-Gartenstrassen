"""Experimental endpoint-dual-aware CGAL ownership candidates.

Preserve the full polygon partition. For each face, inspect two separate
classes of native site pairs: skeleton (ordinary) and segment-endpoint.
Ordinary pairs may yield a unique *candidate*, but endpoint boundaries
must not be silently discarded as ownership evidence. No labels changed.
"""
from shapely.ops import unary_union


def is_endpoint_pair(pair):
	if len(pair)!=2:
		return False
	a,b=pair
	for point,segment in ((a,b),(b,a)):
		if point[0]=="P" and segment[0]=="S":
			x,y=point[1]
			sx,sy,tx,ty=segment[1]
			return (x,y)==(sx,sy) or (x,y)==(tx,ty)
	return False


def audit_endpoint_dual_candidates(polygons,labels,labelled_segments,window,
		*,tolerance=1e-8):
	if len(polygons)!=len(labels) or tolerance<=0:
		raise ValueError("Invalid endpoint-dual audit arguments")
	ordinary=[(geometry,frozenset(pair)) for geometry,pair in labelled_segments
		if not is_endpoint_pair(pair)]
	endpoint=[(geometry,frozenset(pair)) for geometry,pair in labelled_segments
		if is_endpoint_pair(pair)]
	report=[]
	for index,(face,original) in enumerate(zip(polygons,labels)):
		boundary=face.boundary.difference(window.boundary)
		groups=[]
		for sources in (ordinary,endpoint):
			matches=[(line.intersection(boundary),pair)
				for line,pair in sources if line.intersection(boundary).length>tolerance]
			pairs=set(pair for _,pair in matches)
			coverage=unary_union([overlap for overlap,_ in matches]).length if matches else 0.
			groups.append((pairs,coverage))
		skeleton_pairs,skeleton_coverage=groups[0]
		endpoint_pairs,endpoint_coverage=groups[1]
		candidates=(set.intersection(*(set(pair) for pair in skeleton_pairs))
			if len(skeleton_pairs)>=2 else set())
		candidate=next(iter(candidates)) if len(candidates)==1 else None
		# This is not a proof: native endpoint duals might form genuine
		# boundaries of point-site cells. Record conflicts explicitly.
		endpoint_conflicts=sum(candidate not in pair for pair in endpoint_pairs
			) if candidate is not None else None
		if original is not None and candidate is not None and candidate!=original:
			raise ValueError("Experimental candidate contradicts proven label")
		report.append({"face_index":index,
			"originally_proven":original is not None,
			"ordinary_pairs":len(skeleton_pairs),
			"endpoint_pairs":len(endpoint_pairs),
			"ordinary_boundary_m":skeleton_coverage,
			"endpoint_boundary_m":endpoint_coverage,
			"unique_ordinary_candidate":candidate is not None,
			"candidate_matches_original":candidate==original
				if original is not None and candidate is not None else None,
			"candidate_site":({"kind":candidate[0],
				"coordinates":list(candidate[1])} if candidate is not None else None),
			"endpoint_conflicting_pairs":endpoint_conflicts,
			"status":"candidate_only_not_proven" if original is None and candidate is not None
				else "unchanged"})
	return report
