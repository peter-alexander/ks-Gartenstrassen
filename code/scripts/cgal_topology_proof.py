"""Conservative ownership proof from labelled Voronoi boundary incidence.

This is deliberately a *small-network diagnostic*, not the Vienna builder.
No cell is labelled unless every non-window boundary section is covered by
labelled CGAL dual edges and all incident site pairs share one generator.
"""
from shapely.geometry import LineString
from shapely.ops import polygonize, unary_union
from shapely.strtree import STRtree


def reconstruct_test_cells(window, labelled_segments, *, tolerance=1e-7,
		diagnose=False):
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
	if diagnose:
		stats["diagnostic_examples"]=[]
	for face_index,polygon in enumerate(polygons):
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
			if diagnose and len(stats["diagnostic_examples"])<32:
				missing=boundary.difference(unary_union(covered)) if covered else boundary
				# A line can be almost coincident without a positive-length
				# overlap. Report geometric proximity separately from topology.
				missing_parts=[part for part in getattr(missing,"geoms",(missing,))
					if isinstance(part,LineString) and part.length>tolerance]
				all_lines=unary_union(lines)
				proximity=[{
					"length_m":part.length,
					"nearest_input_distance_m":part.distance(all_lines),
					"hausdorff_to_input_m":min(part.hausdorff_distance(line)
						for line in lines),
					"endpoints_to_input_m":[
						part.boundary.geoms[i].distance(all_lines) for i in range(2)]
					} for part in missing_parts]
				stats["diagnostic_examples"].append({
					"face_index":face_index,"reason":"missing_boundary_labels",
					"area_m2":polygon.area,"missing_length_m":missing.length,
					"boundary_length_m":boundary.length,"missing_wkt":missing.wkt,
					"missing_parts":proximity,
					"face_bounds":list(polygon.bounds),
					"labelled_pair_count":len(set(site_pairs))})
			continue
		if len(set(site_pairs))<2:
			if diagnose and len(stats["diagnostic_examples"])<32:
				stats["diagnostic_examples"].append({
					"face_index":face_index,"reason":"insufficient_incidence",
					"area_m2":polygon.area,"face_bounds":list(polygon.bounds),
					"labelled_pair_count":len(set(site_pairs))})
			# One bisector does not reveal which adjacent cell we occupy.
			generators.append(None)
			stats["insufficient_incidence"]+=1
			continue
		common=set.intersection(*(set(p) for p in site_pairs))
		if len(common)!=1:
			generators.append(None)
			stats["conflicting_labels"]+=1
			if diagnose and len(stats["diagnostic_examples"])<32:
				stats["diagnostic_examples"].append({
					"face_index":face_index,"reason":"conflicting_labels",
					"area_m2":polygon.area,"face_bounds":list(polygon.bounds),
					"labelled_pair_count":len(set(site_pairs)),
					"common_site_count":len(common)})
		else:
			generators.append(next(iter(common)))
			stats["proven"]+=1
	return polygons,generators,stats
