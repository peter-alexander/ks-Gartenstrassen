"""Read-only audit of CGAL dual labels along actual shared face boundaries.

Distinguishes positive-length overlap from endpoint contact, missing
coverage and multiply-labelled sections. It does not infer owners.
"""
from shapely.ops import unary_union
from scripts.cgal_internal_dual_audit import _lines


def audit_shared_boundaries(polygons,labels,labelled_segments,*,tolerance=1e-8):
	if len(polygons)!=len(labels) or tolerance<=0:
		raise ValueError("Invalid shared-boundary audit arguments")
	results=[]
	for i,face in enumerate(polygons):
		if labels[i] is not None:
			continue
		for j in range(i+1,len(polygons)):
			shared=face.boundary.intersection(polygons[j].boundary)
			if shared.length<=tolerance:
				continue
			fragments=[]
			touching_only=[]
			for source_id,(line,pair) in enumerate(labelled_segments):
				intersection=shared.intersection(line)
				pieces=list(_lines(intersection))
				if not pieces:
					if shared.intersects(line):
						touching_only.append(source_id)
					continue
				for piece in pieces:
					if piece.length<=tolerance:
						continue
					fragments.append((source_id,piece,frozenset(pair)))
			covered=unary_union([p for _,p,_ in fragments]) if fragments else shared.intersection(shared.boundary)
			missing=shared.difference(covered)
			# Noding breaks the shared boundary into atomic spans, allowing
			# a precise list of contradictory labels on identical spans.
			noded=unary_union([shared,*(p for _,p,_ in fragments)])
			atomics=[]
			for atomic in _lines(noded):
				for a,b in zip(atomic.coords,list(atomic.coords)[1:]):
					from shapely.geometry import LineString
					part=LineString((a,b))
					if part.length<=tolerance or part.representative_point().distance(shared)>tolerance:
						continue
					covering=[(source_id,pair) for source_id,fragment,pair in fragments
						if fragment.intersection(part).length>=part.length-tolerance]
					if not covering:
						continue
					pairs={pair for _,pair in covering}
					atomics.append({"length_m":part.length,
						"source_indices":sorted({k for k,_ in covering}),
						"distinct_pairs":len(pairs),
						"multiply_labelled":len(pairs)>1})
			results.append({"face_indices":[i,j],
				"shared_length_m":shared.length,
				"covered_length_m":covered.length,
				"missing_length_m":missing.length,
				"source_fragment_count":len(fragments),
				"touching_only_sources":touching_only,
				"atomic_spans":atomics,
				"multiply_labelled_spans":sum(v["multiply_labelled"] for v in atomics),
				"distinct_source_pairs":len({pair for _,_,pair in fragments})})
	return results
