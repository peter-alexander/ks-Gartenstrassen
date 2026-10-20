"""Conservative ownership proof from labelled Voronoi boundary incidence.

This is deliberately a *small-network diagnostic*, not the Vienna builder.
No cell is labelled unless every non-window boundary section is covered by
labelled CGAL dual edges and all incident site pairs share one generator.
"""
from shapely.geometry import LineString, Point
from shapely.ops import polygonize, unary_union
from shapely.strtree import STRtree


def reconstruct_test_cells(window, labelled_segments, *, tolerance=1e-7,
		diagnose=False,noded_provenance=False,carried_provenance=False):
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
	if noded_provenance and carried_provenance:
		raise ValueError("Choose only one experimental provenance mode")
	if carried_provenance:
		from scripts.cgal_carried_provenance import carried_provenance as build
		arrangement,carried_edges=build(window,lines,pairs)
		polygons=list(polygonize(arrangement))
		atomic=[item[0] for item in carried_edges]
		edge_pairs=[item[1] for item in carried_edges]
		noded_tree=STRtree(atomic)
		epsilon=min(tolerance,1e-8)
	elif noded_provenance:
		noded=unary_union([window.boundary,*lines])
		polygons=list(polygonize(noded))
		# Split the same noded graph as polygonize into atomic straight edges.
		atomic=[]
		def collect(geom):
			if geom.geom_type=="LineString":
				coords=list(geom.coords)
				for a,b in zip(coords,coords[1:]):
					if a!=b:
						atomic.append(LineString((a,b)))
			elif hasattr(geom,"geoms"):
				for part in geom.geoms:
					collect(part)
		collect(noded)
		tree=STRtree(lines)
		# Track source pairs on the noded edges. Reject unmatched edges
		# rather than replacing provenance with nearest-generator guesses.
		epsilon=min(tolerance,1e-8)
		edge_pairs=[]
		for edge in atomic:
			matches=set()
			for index in tree.query(edge.buffer(epsilon)):
				i=int(index)
				if (edge.distance(lines[i])<=epsilon and
						all(Point(coord).distance(lines[i])<=epsilon
							for coord in edge.coords)):
					matches.add(pairs[i])
			edge_pairs.append(matches)
		noded_tree=STRtree(atomic)
	else:
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
		if noded_provenance or carried_provenance:
			for index in noded_tree.query(boundary):
				i=int(index)
				edge=atomic[i]
				# Both inputs belong to the same noded arrangement.
				# Test edge membership, not independently rounded overlap.
				if edge.interpolate(0.5,normalized=True).distance(boundary)>epsilon:
					continue
				if not edge_pairs[i]:
					continue
				covered.append(edge)
				site_pairs.extend(edge_pairs[i])
		else:
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
