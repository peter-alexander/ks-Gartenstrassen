"""Exploratory native CGAL Face GeoJSON BEFORE strict topology/GEOS checks.

Reads the cached F/P/H/S/E/Z stream; no CGAL rerun, site/polygon spatial
matching, SIS, polygon validity check, clipping, or dissolve. Segment Faces and selected original inner-vertex Point Faces are
written individually with their original input edge_id. Curved halfedges
retain CGAL's sampled points when their chain fits native endpoints.
When a halfedge fails the strict join (e.g. Face 282), ONLY THAT halfedge
is replaced by its native CCB endpoint chord and flagged. The preview is
NOT a valid GIS topology or a substitute for the approved final export.
"""
from collections import Counter
import json
import math
from pathlib import Path
import tempfile
import os

from pyproj import Transformer

from scripts.cgal_segment_input import SCALE
from scripts.cgal_native_faces import _xy, _distance, _join_halfedge, MAX_JOIN_ERROR_M


def _values(fields,line_number,*,face_number=None,kind=None):
	if len(fields)!=5:
		raise ValueError(f"Nativer Face-Stream Zeile {line_number}: 4 Koordinaten erforderlich")
	result=[float(value) for value in fields[1:]]
	if not all(math.isfinite(value) for value in result):
		raise ValueError(f"Nativer Face-Stream Zeile {line_number}, Face {face_number}, "
			f"Typ {kind}: Koordinate nicht endlich; Rohwerte: {fields!r}")
	return result


def _supporting_key(values,line_number):
	for value in values:
		if abs(value-round(value))>1e-5:
			raise ValueError(
				f"Nativer Face-Stream Zeile {line_number}: Eingabesegment nicht im Millimeterraster")
	a=(round(values[0]),round(values[1]))
	b=(round(values[2]),round(values[3]))
	return tuple(sorted((a,b)))


def _point_key(values,line_number):
	if len(values)!=2 or not all(math.isfinite(v) for v in values):
		raise ValueError(f"Nativer Face-Stream Zeile {line_number}: ungültige Punkt-Site")
	if any(abs(v-round(v))>1e-5 for v in values):
		raise ValueError(f"Nativer Face-Stream Zeile {line_number}: Punkt-Site nicht im Millimeterraster")
	return tuple(round(v) for v in values)


def _envelope_overlaps(coords,bounds):
	xmin,ymin,xmax,ymax=coords
	a,b,c,d=bounds
	return not (xmax<a or xmin>c or ymax<b or ymin>d)


def _build_preview_ring(edges,face_no):
	"""Use native curves where possible; clearly flag endpoint-chord fallback."""
	ring=[]
	fallbacks=[]
	for i,(start,end,chords) in enumerate(edges,1):
		try:
			coords=_join_halfedge(chords,start,end,
				face_number=face_no,halfedge_number=i)
		except ValueError as exc:
			coords=[start,end]
			fallbacks.append({
				"halfedge":i,"reason":str(exc),
				"fallback":"native_ccb_endpoint_chord"})
		if ring:
			distance=_distance(ring[-1],coords[0])
			if distance>MAX_JOIN_ERROR_M:
				fallbacks.append({
					"halfedge":i,"reason":f"Halfedge seam gap {distance:.9g} m",
					"fallback":"direct_connection_to_next_ccb_start"})
				ring.append(coords[0])
			else:
				coords[0]=ring[-1]
			ring.extend(coords[1:])
		else:
			ring.extend(coords)
	if ring:
		gap=_distance(ring[0],ring[-1])
		if gap>MAX_JOIN_ERROR_M:
			fallbacks.append({
				"halfedge":None,"reason":f"Unclosed CCB ring {gap:.9g} m",
				"fallback":"closing_line_segment"})
			ring.append(ring[0])
		else:
			ring[-1]=ring[0]
	return ring,fallbacks


def _new_report_file(path,report):
	with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",
			dir=path.parent,prefix="."+path.name+".",suffix=".tmp",
			delete=False) as out:
		temp=Path(out.name)
		try:
			json.dump(report,out,ensure_ascii=False,indent=2,allow_nan=False)
			out.write("\n")
			out.flush()
			os.replace(temp,path)
		finally:
			temp.unlink(missing_ok=True)


def write_preview(stream_path,owners,origin,aoi,out,report,*,progress=None,identity=None,point_owners=None):
	"""Write WGS84 GeoJSON for native segment Faces before geometry validation.

	The resulting polygons are UNCHECKED and UNCLIPPED (bbox filtered
	against the AOI only). Bad halfedge curves are rendered as marked
	straight CCB chords; invalid polygons are intentionally retained.
	Only native point Faces keyed to unique INNER vertices of original
	LINEAR_USE features are included; original endpoints stay omitted.
	Do not feed these polygons into SIS or later GIS calculations.
	"""
	stream_path=Path(stream_path)
	out=Path(out)
	report=Path(report)
	for target in (out,report):
		if target.exists() or target.is_symlink():
			raise FileExistsError(f"CGAL-Vorschau existiert bereits: {target}")
	if not aoi.is_valid or aoi.is_empty:
		raise ValueError("CGAL-Vorschau: ungültige AOI")
	out.parent.mkdir(parents=True,exist_ok=True)
	report.parent.mkdir(parents=True,exist_ok=True)
	to_wgs=Transformer.from_crs(31256,4326,always_xy=True).transform
	bounds=aoi.bounds
	if point_owners is None:
		point_owners={}
	stats=Counter({
		"point_faces_exported":0,
		"point_faces_without_inner_original_vertex_omitted":0,
		"segment_faces_exported":0,
		"faces_with_fallback":0,
		"fallback_halfedges_or_seams":0,
		"segment_faces_exported":0,
		"segment_faces_outside_aoi_bbox":0,
		"artificial_frame_faces_omitted":0,
		"degenerate_faces_omitted":0,
	})
	first_issues=[]
	face_no=0
	generator_type=None
	state="outside"
	owner=None
	edges=[]
	start=end=None
	chords=[]
	envelope=None

	def grow(point):
		nonlocal envelope
		x,y=point
		if envelope is None:
			envelope=[x,y,x,y]
		else:
			envelope[0]=min(envelope[0],x)
			envelope[1]=min(envelope[1],y)
			envelope[2]=max(envelope[2],x)
			envelope[3]=max(envelope[3],y)

	with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",
			dir=out.parent,prefix="."+out.name+".",
			suffix=".tmp",delete=False) as target:
		temp=Path(target.name)
		try:
			target.write('{"type":"FeatureCollection","features":[\n')
			first=True
			with stream_path.open(encoding="utf-8") as source:
				for lineno,raw in enumerate(source,1):
					fields=raw.split()
					if not fields:
						continue
					kind=fields[0]
					if kind in ("F","P"):
						if state!="outside":
							raise ValueError(f"CGAL-Vorschau Zeile {lineno}: verschachtelte Face")
						face_no+=1
						generator_type="segment" if kind=="F" else "inner_point"
						if kind=="F":
							owner=owners.get(_supporting_key(_values(fields,lineno,face_number=face_no,kind=kind),lineno))
						else:
							if len(fields)!=3:
								raise ValueError(f"CGAL-Vorschau Zeile {lineno}: Punkt-Site ohne 2 Koordinaten")
							point=_point_key([float(value) for value in fields[1:]],lineno)
							owner=point_owners.get(point)
							if owner is None:
								stats["point_faces_without_inner_original_vertex_omitted"]+=1
						edges=[]
						envelope=None
						state="face"
					elif kind=="H":
						if state!="face":
							raise ValueError(f"CGAL-Vorschau Zeile {lineno}: unerwartete Halfedge")
						values=_values(fields,lineno,face_number=face_no,kind=kind)
						start=_xy(values[0],values[1],origin)
						end=_xy(values[2],values[3],origin)
						if owner is not None:
							grow(start)
							grow(end)
						chords=[]
						state="edge"
					elif kind in ("S","R","L"):
						if state!="edge":
							raise ValueError(f"CGAL-Vorschau Zeile {lineno}: Kurve ohne Halfedge")
						if kind!="S":
							raise ValueError(f"CGAL-Vorschau Zeile {lineno}: "
								"unendliche Kante in nativer begrenzter Face")
						if owner is not None:
							values=_values(fields,lineno)
							a=_xy(values[0],values[1],origin)
							b=_xy(values[2],values[3],origin)
							grow(a)
							grow(b)
							chords.append((a,b))
					elif kind=="E":
						if state!="edge" or len(fields)!=1:
							raise ValueError(f"CGAL-Vorschau Zeile {lineno}: unerwartetes E")
						if owner is not None:
							edges.append((start,end,chords))
						state="face"
					elif kind=="Z":
						if state!="face" or len(fields)!=1:
							raise ValueError(f"CGAL-Vorschau Zeile {lineno}: unerwartetes Z")
						state="outside"
						if owner is None:
							if generator_type=="segment":
								stats["artificial_frame_faces_omitted"]+=1
							continue
						if envelope is None or not _envelope_overlaps(envelope,bounds):
							stats["segment_faces_outside_aoi_bbox"]+=1
							continue
						ring,issues=_build_preview_ring(edges,face_no)
						if len(ring)<4 or len(set(ring))<3:
							stats["degenerate_faces_omitted"]+=1
							if len(first_issues)<50:
								first_issues.append({"face_number":face_no,
									"edge_id":owner,"reason":"Fewer than three distinct ring vertices"})
							continue
						if issues:
							stats["faces_with_fallback"]+=1
							stats["fallback_halfedges_or_seams"]+=len(issues)
							if len(first_issues)<50:
								first_issues.append({
									"face_number":face_no,"edge_id":owner,
									"issues":issues[:10]})
						xs,ys=to_wgs([pt[0] for pt in ring],[pt[1] for pt in ring])
						if not all(math.isfinite(v) for v in (*xs,*ys)):
							raise ValueError(f"Face {face_no}: WGS84-Transformation ungültig")
						feature={"type":"Feature",
							"properties":{
								"edge_id":owner,"face_number":face_no,
								"generator_type":generator_type,
								"preview_only":True,
								"fallback":bool(issues),
								"fallback_count":len(issues),
								"not_validated":True},
							"geometry":{"type":"Polygon",
								"coordinates":[list(map(list,zip(xs,ys)))]}}
						if not first:
							target.write(",\n")
						first=False
						json.dump(feature,target,ensure_ascii=False,
							separators=(",",":"),allow_nan=False)
						stats["point_faces_exported" if generator_type=="inner_point" else "segment_faces_exported"]+=1
						if progress and face_no%20000==0:
							progress(f"CGAL-Vorschau: {face_no:,} Faces gelesen, "
								f"{stats['segment_faces_exported']:,} ausgegeben")
					else:
						raise ValueError(f"CGAL-Vorschau Zeile {lineno}: unbekannter Typ {kind}")
			if state!="outside":
				raise ValueError("CGAL-Vorschau: nativer Face-Stream unvollständig")
			if not (stats["segment_faces_exported"]+stats["point_faces_exported"]):
				raise ValueError("CGAL-Vorschau enthielt keine darstellbaren Segment-Faces")
			target.write('\n],"metadata":{"schema":"native-cgal-faces-raw-preview-v1",'
				'"geometry_validated":false,"dissolved":false,'
				'"clipped_to_aoi":false,"bbox_filtered":true,'
				'"point_faces_assigned":"original_inner_only",'
				'"fallback_geometry":"CCB endpoint chord where needed"}}\n')
			target.flush()
			os.replace(temp,out)
		finally:
			temp.unlink(missing_ok=True)
	stats["face_records_read"]=face_no
	summary={
		"schema":"native-cgal-faces-raw-preview-v1",
		"output_geojson":str(out),
		"source_face_stream":str(stream_path),
		"preview_input_identity":identity,
		"native_face_records":face_no,
		"stats":dict(stats),
		"first_issues":first_issues,
		"geometry_validated":False,
		"clipped_to_exact_aoi":False,
		"bbox_filtered_to_aoi":True,
		"dissolved_by_edge_id":False,
		"note":"Ungeprüfte Einzel-Faces; bei fehlerhaften Randkurven wird nur "
			"für die betroffenen Halfedges die native Endpunkt-Sehne verwendet. "
			"Die Datei ist ausschließlich zur Darstellung in QGIS gedacht."
	}
	_new_report_file(report,summary)
	print(f"CGAL-Vorschau: {stats['segment_faces_exported']:,} Segment-Faces, "
		f"{stats['point_faces_exported']:,} innere Punkt-Faces, "
		f"{stats['faces_with_fallback']:,} Faces mit "
		f"markierten Ersatz-Sehnen; {out}",flush=True)
	return summary
