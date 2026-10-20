"""Experimental CGAL source-provenance-preserving noding.

Split each *labelled source segment* at nodes of a common arrangement.
The generator pair travels with each source fragment. The canonical
fragment key is used only to identify matching arrangement edges, never
to guess a site from proximity or from a polygon centroid.
"""
from shapely.geometry import LineString, Point
from shapely.ops import unary_union
from shapely.strtree import STRtree


def _key(a,b,decimals=8):
	a=tuple(round(v,decimals) for v in a)
	b=tuple(round(v,decimals) for v in b)
	return tuple(sorted((a,b)))


def carried_provenance(window,lines,pairs,*,tolerance=1e-8):
	"""Return arrangement and labels by atomic edge coordinate key.

	Source segments with conflicting generator pairs are explicitly
	ambiguous. Unlabelled window edges have no generating-site pair.
	Only appropriate for small independent CGAL QA fixtures.
	"""
	if len(lines)!=len(pairs) or tolerance<=0:
		raise ValueError("Invalid labelled CGAL source")
	arrangement=unary_union([window.boundary,*lines])
	nodes=set()
	atomic=[]
	def collect(geometry):
		if geometry.geom_type=="LineString":
			coords=list(geometry.coords)
			for start,end in zip(coords,coords[1:]):
				if start!=end:
					nodes.add(start)
					nodes.add(end)
					atomic.append((start,end))
		elif hasattr(geometry,"geoms"):
			for part in geometry.geoms:
				collect(part)
	collect(arrangement)
	# Spatial node index avoids the quadratic all-nodes/all-lines loop.
	node_points=[Point(node) for node in sorted(nodes)]
	node_tree=STRtree(node_points)
	labels={}
	# Transfer source identity by splitting source segments at common nodes.
	# Boundary recognition below is a key join, not GEOS line intersection.
	for source_id,line in enumerate(lines):
		positions={0.,line.length}
		for index in node_tree.query(line.buffer(tolerance)):
			point=node_points[int(index)]
			if point.distance(line)<=tolerance:
				positions.add(line.project(point))
		ordered=sorted(positions)
		for lo,hi in zip(ordered,ordered[1:]):
			if hi-lo<=tolerance:
				continue
			a=line.interpolate(lo).coords[0]
			b=line.interpolate(hi).coords[0]
			key=_key(a,b)
			labels.setdefault(key,set()).add(pairs[source_id])
	edges=[]
	for a,b in atomic:
		key=_key(a,b)
		edges.append((LineString((a,b)),frozenset(labels.get(key,()))))
	return arrangement,edges
