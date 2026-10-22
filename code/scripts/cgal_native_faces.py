"""Read native CGAL face CCB geometry; no site/polygon spatial matching.

Each F record originates from a real Voronoi Face and already contains
the *supporting input segment* for its CGAL generator. Halfedges are
exported in native counterclockwise order. CGAL linearizes parabolic
bisectors while drawing each edge; we reassemble those chord chains
using the endpoints CGAL supplies for the *same* halfedge.

Point-site cells are absent from the stream by design.
"""
from collections import Counter, defaultdict
import math
from pathlib import Path

from shapely.geometry import LineString, Polygon
from shapely.ops import linemerge
from shapely.validation import explain_validity

from scripts.cgal_segment_input import SCALE

# Only submillimetre discrepancies in CGAL's float serialization may
# be snapped; a larger mismatch must remain an explicit geometry error.
MAX_JOIN_ERROR_M=0.0005


def _xy(x,y,origin):
	return (float(x)/SCALE+origin[0],float(y)/SCALE+origin[1])


def _distance(a,b):
	return math.hypot(a[0]-b[0],a[1]-b[1])


def _join_halfedge(chords,start,end,*,face_number,halfedge_number):
	lines=[LineString((a,b)) for a,b in chords if a!=b]
	if not lines:
		raise ValueError(f"Face {face_number}, Halfedge {halfedge_number}: "
			"CGAL hat keine nichtdegenerierte Randkurve ausgegeben")
	if len(lines)==1:
		coords=list(lines[0].coords)
	else:
		merged=linemerge(lines)
		if not isinstance(merged,LineString):
			raise ValueError(f"Face {face_number}, Halfedge {halfedge_number}: "
				"CGAL-Randkurve nicht zusammenhängend")
		coords=list(merged.coords)
	forwards=_distance(coords[0],start)+_distance(coords[-1],end)
	backwards=_distance(coords[-1],start)+_distance(coords[0],end)
	if backwards<forwards:
		coords.reverse()
	if (_distance(coords[0],start)>MAX_JOIN_ERROR_M or
			_distance(coords[-1],end)>MAX_JOIN_ERROR_M):
		raise ValueError(f"Face {face_number}, Halfedge {halfedge_number}: "
			"CGAL-Randkurve weicht von CCB-Endpunkten ab")
	coords[0]=start
	coords[-1]=end
	return coords


def read_native_faces(path,owners,origin,aoi,*,progress=None):
	"""Return native segment polygons grouped by their original edge_id.

	The owner key comes strictly from a CGAL face's supporting original
	segment. No STRtree lookup, invented query point, or nearest-site rule.
	"""
	if aoi.is_empty or not aoi.is_valid:
		raise ValueError("CGAL-Face-Prüfgebiet muss gültig und nicht leer sein")
	minx,miny,maxx,maxy=aoi.bounds
	groups=defaultdict(list)
	stats=Counter()
	face_number=0
	edge_number=0
	face_owner=None
	face_ring=None
	halfedge_start=None
	halfedge_end=None
	chords=[]
	excluded=False
	state="outside"
	with Path(path).open(encoding="utf-8") as stream:
		for lineno,raw in enumerate(stream,1):
			fields=raw.split()
			if not fields:
				continue
			kind=fields[0]
			if kind=="F":
				if state!="outside" or len(fields)!=5:
					raise ValueError(f"CGAL-Faces Zeile {lineno}: F unerwartet")
				values=list(map(float,fields[1:]))
				if not all(math.isfinite(x) for x in values):
					raise ValueError(f"CGAL-Faces Zeile {lineno}: ungültiger Site-Schlüssel")
				pairs=[(int(round(values[0])),int(round(values[1]))),
					(int(round(values[2])),int(round(values[3])))]
				for i,value in enumerate(values):
					if abs(value-round(value))>1e-5:
						raise ValueError(f"CGAL-Faces Zeile {lineno}: "
							"Support-Segment nicht im Millimeterraster")
				key=tuple(sorted(pairs))
				face_owner=owners.get(key)
				excluded=face_owner is None
				face_ring=[]
				state="face"
				face_number+=1
				edge_number=0
				continue
			if kind=="H":
				if state!="face" or len(fields)!=5:
					raise ValueError(f"CGAL-Faces Zeile {lineno}: H unerwartet")
				values=list(map(float,fields[1:]))
				if not all(math.isfinite(x) for x in values):
					raise ValueError(f"CGAL-Faces Zeile {lineno}: ungültiger Halfedge")
				halfedge_start=_xy(values[0],values[1],origin)
				halfedge_end=_xy(values[2],values[3],origin)
				chords=[]
				state="halfedge"
				edge_number+=1
				continue
			if kind in ("S","R","L"):
				if state!="halfedge" or len(fields)!=5:
					raise ValueError(f"CGAL-Faces Zeile {lineno}: {kind} unerwartet")
				if kind!="S":
					raise ValueError(f"CGAL-Faces Zeile {lineno}: "
						"unendliche Dualkante in begrenzter Voronoi-Face")
				if excluded:
					continue
				coords=[float(x) for x in fields[1:]]
				if not all(math.isfinite(x) for x in coords):
					raise ValueError(f"CGAL-Faces Zeile {lineno}: ungültiger Stützpunkt")
				chords.append((_xy(coords[0],coords[1],origin),
					_xy(coords[2],coords[3],origin)))
				continue
			if kind=="E":
				if state!="halfedge" or len(fields)!=1:
					raise ValueError(f"CGAL-Faces Zeile {lineno}: E unerwartet")
				if not excluded:
					coords=_join_halfedge(
						chords,halfedge_start,halfedge_end,
						face_number=face_number,halfedge_number=edge_number)
					if not face_ring:
						face_ring.extend(coords)
					else:
						gap=_distance(face_ring[-1],coords[0])
						if gap>MAX_JOIN_ERROR_M:
							raise ValueError(f"Face {face_number}: "
								f"benachbarte Halfedges haben {gap:.6g} m Lücke")
						coords[0]=face_ring[-1]
						face_ring.extend(coords[1:])
				state="face"
				continue
			if kind=="Z":
				if state!="face" or len(fields)!=1 or edge_number<2:
					raise ValueError(f"CGAL-Faces Zeile {lineno}: Z unerwartet")
				if excluded:
					stats["frame_faces_omitted"]+=1
				else:
					gap=_distance(face_ring[0],face_ring[-1])
					if gap>MAX_JOIN_ERROR_M:
						raise ValueError(f"Face {face_number}: "
							f"CCB nicht geschlossen ({gap:.6g} m)")
					face_ring[-1]=face_ring[0]
					# Geometrisch beweisbar außerhalb des Prüfgebiets:
					# Ist die gesamte Face-Hülle disjunkt von der AOI-Hülle,
					# kann auch eine ungültige Face die AOI nicht erreichen.
					# Noch vor Polygon() / is_valid / intersection() ausscheiden.
					# Kein Flächen-Fallback und keine Geometriereparatur.
					bx0=min(pt[0] for pt in face_ring)
					bx1=max(pt[0] for pt in face_ring)
					by0=min(pt[1] for pt in face_ring)
					by1=max(pt[1] for pt in face_ring)
					if bx1<minx or bx0>maxx or by1<miny or by0>maxy:
						stats["segment_faces_outside_aoi_bbox"]+=1
						state="outside"
						continue
					polygon=Polygon(face_ring)
					if polygon.is_empty or not polygon.is_valid or polygon.area<=0:
						raise ValueError(f"Face {face_number}, edge_id {face_owner}: "
							f"native Polygongeometrie ungültig "
							f"({explain_validity(polygon)}; "
							f"{len(face_ring)} Ringpunkte; "
							f"{edge_number} Halfedges; "
							f"Fläche {polygon.area:.12g} m²). "
							"Gespeicherten Face-Stream mit "
							"scripts.inspect_cgal_native_face untersuchen.")
					clipped=polygon.intersection(aoi)
					if not clipped.is_empty and clipped.area>0:
						if not clipped.is_valid:
							raise ValueError(f"Face {face_number}: "
								"Clipping der nativen CGAL-Face ungültig")
						groups[face_owner].append(clipped)
						stats["segment_faces_inside_window"]+=1
					else:
						stats["segment_faces_outside_window"]+=1
				if progress and face_number%20000==0:
					progress(f"CGAL-Faces: {face_number:,} native Segment-Faces verarbeitet")
				state="outside"
				continue
			raise ValueError(f"CGAL-Faces Zeile {lineno}: unbekannter Typ {kind!r}")
	if state!="outside":
		raise ValueError("CGAL-Face-Export ist abgeschnitten")
	stats["native_face_records"]=face_number
	stats["original_edge_ids"]=len(groups)
	return groups,dict(stats)
