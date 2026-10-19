"""Experimental genuine segment-site Voronoi kernel for GIP result axes.

Not a polygon exporter: Boost's unbounded cells and parabolic edges require
explicit boundary reconstruction before use with SIS and tile-independent output.
No silent fallback to point sampling is permitted.
"""
import math

from shapely.geometry import LineString
from shapely.strtree import STRtree

SCALE=1000  # One millimetre integer-grid input to Boost.


def _segments(axes):
	"""Return input segments with owner identity, preserving all bends."""
	segments=[]
	for edge_id,line in axes:
		if not isinstance(line,LineString) or line.is_empty or not line.is_valid:
			raise ValueError(f"{edge_id}: gültiger LineString erforderlich")
		for a,b in zip(line.coords,line.coords[1:]):
			pa=tuple(a[:2])
			pb=tuple(b[:2])
			if pa==pb:
				continue
			segments.append((str(edge_id),pa,pb))
	if not segments:
		raise ValueError("Keine Liniensegmente vorhanden")
	return segments


def construct_segment_diagram(axes,*,scale=SCALE):
	"""Compute the true Boost segment Voronoi graph, not sampled points.

	Returns (pyvoronoi instance, source owners). The graph is not yet a
	polygonal partition. Source segments must not cross/overlap internally:
	such geometry needs noding and owner resolution before construction.
	"""
	try:
		import pyvoronoi
	except ImportError as exc:
		raise RuntimeError("pyvoronoi==1.2.8 installieren") from exc
	if not isinstance(scale,int) or scale<1:
		raise ValueError("Ganzzahliger positiver Maßstab erforderlich")
	segments=_segments(axes)
	x0=min(min(a[0],b[0]) for _,a,b in segments)
	y0=min(min(a[1],b[1]) for _,a,b in segments)
	rounded={}
	for owner,a,b in segments:
		pa=(round((a[0]-x0)*scale),round((a[1]-y0)*scale))
		pb=(round((b[0]-x0)*scale),round((b[1]-y0)*scale))
		if pa==pb:
			raise ValueError(f"{owner}: Liniensegment verschwindet im Integer-Raster")
		key=tuple(sorted((pa,pb)))
		if key in rounded and rounded[key]!=owner:
			raise ValueError(f"Überlappendes Segment verschiedener edge_id: {owner}, {rounded[key]}")
		rounded[key]=owner
	# Boost.Polygon does not accept proper crossings. Do not feed it
	# intersecting GIP axes and pretend the output is scientifically valid.
	keys=list(rounded)
	geoms=[LineString(pair) for pair in keys]
	tree=STRtree(geoms)
	for i,geom in enumerate(geoms):
		for j in tree.query(geom):
			j=int(j)
			if j<=i:
				continue
			other=geoms[j]
			intersection=geom.intersection(other)
			if intersection.is_empty:
				continue
			if intersection.geom_type=="Point":
				p=(intersection.x,intersection.y)
				ends_a=(tuple(geom.coords[0]),tuple(geom.coords[-1]))
				ends_b=(tuple(other.coords[0]),tuple(other.coords[-1]))
				if p in ends_a and p in ends_b:
					continue
			raise ValueError(
				f"Segmentkreuzung/-überlappung vor Voronoi-Konstruktion: "
				f"{rounded[keys[i]]}, {rounded[keys[j]]}")
	diagram=pyvoronoi.Pyvoronoi(scale)
	owners=[]
	for key in keys:
		a,b=key
		diagram.AddSegment([[a[0]/scale,a[1]/scale],
			[b[0]/scale,b[1]/scale]])
		owners.append(rounded[key])
	diagram.Construct()
	return diagram,owners
