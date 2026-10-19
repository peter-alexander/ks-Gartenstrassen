"""Experimental genuine segment-site Voronoi kernel for GIP result axes.

Not a polygon exporter: Boost's unbounded cells and parabolic edges require
explicit boundary reconstruction before use with SIS and tile-independent output.
No silent fallback to point sampling is permitted.
"""

from shapely.geometry import LineString, Point
from time import perf_counter
from threading import Event, Thread
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


def _noded_segments(axes, *, scale=SCALE, progress=None):
	"""Node all crossings, preserving site ownership and rejecting ambiguity."""
	started=perf_counter()
	def report(message):
		if progress is not None:
			progress(message)
	report(f"Segmentaufbereitung: {len(axes):,} Achsen einlesen")
	segments=_segments(axes)
	x0=min(min(a[0],b[0]) for _,a,b in segments)
	y0=min(min(a[1],b[1]) for _,a,b in segments)
	inputs={}
	collapsed_segments=0
	for edge_id,line in axes:
		owner=str(edge_id)
		# Quantize the entire polyline, not independent segment pairs.
		# Consecutive sub-millimetre vertices are redundant in the
		# representable Boost geometry; keep their surviving neighbours.
		quantized=[]
		for coordinate in line.coords:
			point=(round((coordinate[0]-x0)*scale),
				round((coordinate[1]-y0)*scale))
			if quantized and point==quantized[-1]:
				collapsed_segments+=1
				continue
			quantized.append(point)
		if len(quantized)<2:
			raise ValueError(
				f"{owner}: gesamte Achse verschwindet im Integer-Raster")
		for pa,pb in zip(quantized,quantized[1:]):
			key=tuple(sorted((pa,pb)))
			inputs.setdefault(key,set()).add(owner)
	report(f"Segmentaufbereitung: {len(inputs):,} eindeutige Segmente, "
		f"{collapsed_segments:,} kurze Kanten zusammengefasst "
		f"({perf_counter()-started:.1f} s)")
	if any(len(owners)>1 for owners in inputs.values()):
		raise ValueError("Deckungsgleiche Segmente unterschiedlicher edge_id")
	source=[LineString(pair) for pair in inputs]
	report(f"Noding (GEOS unary_union): {len(source):,} Segmente; Start")
	step=perf_counter()
	stop=Event()
	def heartbeat():
		while not stop.wait(30):
			report(f"Noding (GEOS unary_union): läuft seit "
				f"{perf_counter()-step:.0f} s ({len(source):,} Eingabesegmente)")
	worker=Thread(target=heartbeat,daemon=True)
	if progress is not None:
		worker.start()
	try:
		noded=unary_union(source)
	finally:
		stop.set()
		if progress is not None:
			worker.join()
	report(f"Noding (GEOS unary_union): beendet in {perf_counter()-step:.1f} s")
	parts=list(noded.geoms) if hasattr(noded,"geoms") else [noded]
	tree=STRtree(source)
	result={}
	report(f"Segmentzuordnung: {len(parts):,} genodete Linien; Start")	
	step=perf_counter()
	collapsed_after_noding=0
	collapsed_owners=set()
	for piece_number,piece in enumerate(parts,1):
		if piece_number%10000==0:
			elapsed=perf_counter()-step
			report(f"Segmentzuordnung: {piece_number:,}/{len(parts):,} "
				f"({100*piece_number/len(parts):.1f} %), {elapsed:.1f} s; "
				f"{len(result):,} Teilsegmente")
		if not isinstance(piece,LineString) or piece.length==0:
			continue
		for a,b in zip(piece.coords,piece.coords[1:]):
			key=tuple(sorted((tuple(round(v) for v in a[:2]),
				tuple(round(v) for v in b[:2]))))
			mid=Point((a[0]+b[0])/2,(a[1]+b[1])/2)
			owners=set()
			# Query the actual noded segment: no GEOS buffer allocation per piece.
			# Its bounding box includes every source that contains its midpoint.
			for index in tree.query(piece):
				index=int(index)
				if source[index].distance(mid)<=0.00001:
					owners.update(inputs[tuple(sorted(
						(tuple(map(int,source[index].coords[0])),
						tuple(map(int,source[index].coords[-1])))))])
			if len(owners)!=1:
				raise ValueError(
					"Unklare Segmentzuordnung an einer Kreuzung/Überlappung")
			owner=next(iter(owners))
			if key[0]==key[1]:
				# GEOS may split a valid integer-grid edge at a fractional
				# intersection. This sub-grid fragment cannot be encoded as
				# a Boost site; adjacent surviving segments represent its
				# geometry to the declared millimetre resolution.
				collapsed_after_noding+=1
				collapsed_owners.add(owner)
				continue
			if key in result and result[key]!=owner:
				raise ValueError("Mehrdeutige edge_id nach Noding")
			result[key]=owner
	# Quantization can move intersections onto unrelated sites. Reject such
	# configurations rather than silently changing topological ownership.
	if not result:
		raise ValueError("Noding lieferte keine gültigen Segmente")
	missing=collapsed_owners-set(result.values())
	if missing:
		raise ValueError(
			"Achsen nach Noding vollständig im Integer-Raster verschwunden: "
			+", ".join(sorted(missing)[:10]))
	report(f"Segmentzuordnung: fertig, {len(result):,} Segmente, "
		f"{collapsed_after_noding:,} nach Noding unter 1 mm "
		f"({perf_counter()-step:.1f} s)")
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
