"""Conservative ownership proof from labelled Voronoi boundary incidence.

This is deliberately a *small-network diagnostic*, not the Vienna builder.
No cell is labelled unless every non-window boundary section is covered by
labelled CGAL dual edges and all incident site pairs share one generator.
"""
from collections import defaultdict

from shapely.geometry import LineString
from shapely.ops import polygonize, unary_union
from shapely.strtree import STRtree


def reconstruct_test_cells(window, labelled_segments, *, tolerance=1e-7):
	"""Return (polygons, generator labels, diagnostic counters).

	labelled_segments: sequence of (LineString, (site_a, site_b)).
	Sites are hashable immutable CGAL site tuples. Only bounded, straight
	segments are accepted; rays and parabola fragments must first be clipped
	and linearized consistently by the caller.
	"""
	if tolerance<=0 or not window.is_valid or window.is_empty:
		raise ValueError("Ungültiges Fenster oder Toleranz")
	if not labelled_segments:
		raise ValueError("Keine beschrifteten Grenzkanten")
	lines=[]
	pairs=[]
	for geometry,pair in labelled_segments:
		if (not isinstance(geometry,LineString) or geometry.is_empty
				or geometry.length<=0 or len(pair)!=2 or pair[0]==pair[1]):
			raise ValueError("Ungültige beschriftete CGAL-Kante")
		if not geometry.is_valid:
			raise ValueError("Ungültige CGAL-Grenzgeometrie")
		lines.append(geometry)
		pairs.append(frozenset(pair))
	polygons=list(polygonize(unary_union([window.boundary,*lines])))
	tree=STRtree(lines)
	generators=[]
	stats={"proven":0,"missing_boundary_labels":0,"conflicting_labels":0,
		"insufficient_incidence":0}
	for polygon in polygons:
		# Ignore the artificial window edge, which has no generator pair.
		boundary=polygon.boundary.difference(window.boundary)
		if boundary.length<=tolerance:
			generators.append(None)
			stats["insufficient_incidence"]+=1
			continue
		covered=[]
		site_pairs=[]
		for index in tree.query(boundary,predicate="intersects"):
			i=int(index)
			overlap=boundary.intersection(lines[i])
			if overlap.length>tolerance:
				covered.append(overlap)
				site_pairs.append(pairs[i])
		covered_length=(unary_union(covered).length if covered else 0.)
		if boundary.length-covered_length>tolerance:
			generators.append(None)
			stats["missing_boundary_labels"]+=1
			continue
		common=set.intersection(*(set(p) for p in site_pairs))
		if len(common)!=1:
			generators.append(None)
			stats["conflicting_labels"]+=1
		elif len(set(site_pairs))<2:
			# A single bisector never proves which side of it we occupy.
			generators.append(None)
			stats["insufficient_incidence"]+=1
		else:
			generators.append(next(iter(common)))
			stats["proven"]+=1
	return polygons,generators,stats
