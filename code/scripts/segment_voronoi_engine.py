"""Experimental genuine segment-site Voronoi kernel for GIP result axes.

Not a polygon exporter: Boost's unbounded cells and parabolic edges require
explicit boundary reconstruction before use with SIS and tile-independent output.
No silent fallback to point sampling is permitted.
"""

from shapely.geometry import LineString, Point
from shapely.ops import unary_union
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


def _noded_segments(axes, *, scale=SCALE):
	"""Node all crossings, preserving site ownership and rejecting ambiguity."""
	segments=_segments(axes)
	x0=min(min(a[0],b[0]) for _,a,b in segments)
	y0=min(min(a[1],b[1]) for _,a,b in segments)
	inputs={}
	for owner,a,b in segments:
		pa=(round((a[0]-x0)*scale),round((a[1]-y0)*scale))
		pb=(round((b[0]-x0)*scale),round((b[1]-y0)*scale))
		if pa==pb:
			raise ValueError(f"{owner}: Liniensegment verschwindet im Integer-Raster")
		key=tuple(sorted((pa,pb)))
		inputs.setdefault(key,set()).add(owner)
	if any(len(owners)>1 for owners in inputs.values()):
		raise ValueError("Deckungsgleiche Segmente unterschiedlicher edge_id")
	source=[LineString(pair) for pair in inputs]
	noded=unary_union(source)
	parts=list(noded.geoms) if hasattr(noded,"geoms") else [noded]
	tree=STRtree(source)
	result={}
	for piece in parts:
		if not isinstance(piece,LineString) or piece.length==0:
			continue
		for a,b in zip(piece.coords,piece.coords[1:]):
			key=tuple(sorted((tuple(round(v) for v in a[:2]),
				tuple(round(v) for v in b[:2]))))
			if key[0]==key[1]:
				raise ValueError("Segment nach Noding kleiner als Integer-Raster")
			mid=Point((a[0]+b[0])/2,(a[1]+b[1])/2)
			owners=set()
			for index in tree.query(mid.buffer(0.00001)):
				index=int(index)
				if source[index].distance(mid)<=0.00001:
					owners.update(inputs[tuple(sorted(
						(tuple(map(int,source[index].coords[0])),
						tuple(map(int,source[index].coords[-1])))))])
			if len(owners)!=1:
				raise ValueError(
					"Unklare Segmentzuordnung an einer Kreuzung/Überlappung")
			owner=next(iter(owners))
			if key in result and result[key]!=owner:
				raise ValueError("Mehrdeutige edge_id nach Noding")
			result[key]=owner
	# Quantization can move intersections onto unrelated sites. Reject such
	# configurations rather than silently changing topological ownership.
	if not result:
		raise ValueError("Noding lieferte keine gültigen Segmente")
	return result,(x0,y0)


def construct_segment_diagram(axes,*,scale=SCALE):
	"""Create true Boost segment-site graph, with crossings noded first.

	Returns (diagram, owners). Output is NOT a polygonal partition.
	"""
	if not isinstance(scale,int) or scale<1:
		raise ValueError("Ganzzahliger positiver Maßstab erforderlich")
	noded,_origin=_noded_segments(axes,scale=scale)
	try:
		import pyvoronoi
	except ImportError as exc:
		raise RuntimeError("pyvoronoi==1.2.8 installieren") from exc
	diagram=pyvoronoi.Pyvoronoi(scale)
	owners=[]
	for (a,b),owner in sorted(noded.items()):
		diagram.AddSegment([[a[0]/scale,a[1]/scale],
			[b[0]/scale,b[1]/scale]])
		owners.append(owner)
	diagram.Construct()
	return diagram,owners
