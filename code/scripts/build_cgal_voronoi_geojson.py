"""CGAL segment Voronoi from original LINEAR_USE features clipped to SIS.

CGAL constructs the graph from ALL Wiener segments and exports Voronoi
boundaries for the full Vienna extent. No tile-local approximation.
CGAL linearizes parabola arcs for visualization; polygon output is DEBUG ONLY.
"""
import argparse
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile

from pyproj import Transformer
import numpy as np
from shapely import intersection as vector_intersection, area as vector_area, is_empty as vector_is_empty, prepare, union_all, set_precision
from shapely.geometry import LineString, Polygon, MultiPolygon, box, mapping
from shapely.ops import polygonize_full, transform, unary_union
from shapely.strtree import STRtree
from shapely.wkb import loads
from shapely.validation import explain_validity

from scripts.cgal_segment_input import SCALE, _noded_segments
from scripts.cgal_original_line_assignment import assign_by_intersections, write_diagnostics
from scripts.wienwide_grid import checksum, load_aoi, read_manifest
from scripts.wienwide_street import load_street_tile


def _source_records(cache):
	"""Keep original LINEAR_USE object_id, edge_id and metric geometry."""
	with sqlite3.connect(f"file:{Path(cache).resolve()}?mode=ro",uri=True) as db:
		schema=db.execute(
			"SELECT value FROM metadata WHERE key='schema'").fetchone()
		if schema is None or json.loads(schema[0])!="linear-use-original-segments-v2":
			raise ValueError("Original-LINEAR_USE-Cache erforderlich")
		types=db.execute("SELECT value FROM metadata WHERE key=\'base_types\'").fetchone()
		if types is None or tuple(json.loads(types[0]))!=(1,2,6,7,8,9,33,34,35,36,51):
			raise ValueError("LINEAR_USE-Cache mit falscher base_type-Auswahl")
		rows=db.execute(
			"SELECT object_id,edge_id,wkb FROM linear_use_segments "
			"ORDER BY edge_id,object_id").fetchall()
	if not rows:
		raise ValueError("Keine LINEAR_USE-Originalgeometrien")
	return [(str(object_id),str(edge_id),loads(blob))
		for object_id,edge_id,blob in rows]


def _frame(aoi,origin):
	x0,y0=origin
	minx,miny,maxx,maxy=aoi.bounds
	margin=max(1000.,4*math.hypot(maxx-minx,maxy-miny))
	return [(round((x-x0)*SCALE),round((y-y0)*SCALE))
		for x,y in ((minx-margin,miny-margin),(maxx+margin,miny-margin),
			(maxx+margin,maxy+margin),(minx-margin,maxy+margin))]


def _payload(owners,frame):
	for a,b in sorted(owners):
		yield f"{a[0]} {a[1]} {b[0]} {b[1]}\n"
	for a,b in zip(frame,frame[1:]+frame[:1]):
		yield f"{a[0]} {a[1]} {b[0]} {b[1]}\n"


def _window_mask(manifest_path,sis_root,aoi_path,window):
	manifest,aoi=read_manifest(manifest_path)
	if checksum(aoi_path)!=manifest["aoi_sha256"]:
		raise ValueError("SIS und Voronoi verwenden unterschiedliche AOI")
	parts=[]
	for tile_number,tile in enumerate(manifest["tiles"],1):
		if tile_number%100==0:
			print(f"CGAL: SIS-Kachel {tile_number:,}/{len(manifest['tiles']):,}",flush=True)
		full_core=box(*tile["bounds_31256"]).intersection(aoi)
		core=full_core.intersection(window)
		if core.is_empty or core.area==0:
			continue
		# The cache reader verifies the saved geometry against the COMPLETE
		# tile core. Clip to the debug window only after that verification.
		street=load_street_tile(Path(sis_root)/tile["id"]/"street.sqlite",full_core)
		if not street.is_empty:
			parts.append(street.intersection(core))
	if not parts:
		raise ValueError("SIS-Straßenmaske im Debug-Ausschnitt leer")
	result=union_all(parts)
	if not result.is_valid:
		raise ValueError("SIS-Straßenmaske ist ungültig")
	return result,parts


def _record_line(kind,coords,window):
	"""Window CGAL line/ray/segment primitives in EPSG:31256 metric coordinates."""
	a,b=coords
	if kind=="S":
		# CGAL may emit zero-length linearized parabola fragments; these
		# cannot form a polygon boundary and are not valid LineStrings.
		if a==b:
			return None
		line=LineString((a,b))
	elif kind in ("R","L"):
		dx,dy=b[0]-a[0],b[1]-a[1]
		length=math.hypot(dx,dy)
		if length==0 or not math.isfinite(length):
			raise ValueError("Ungültiger CGAL-Ray/Line-Vektor")
		extent=max(1000.,10*math.hypot(
			window.bounds[2]-window.bounds[0],
			window.bounds[3]-window.bounds[1]),
			2*math.dist(a,window.centroid.coords[0]))
		v=(dx/length*extent,dy/length*extent)
		if kind=="R":
			line=LineString((a,(a[0]+v[0],a[1]+v[1])))
		else:
			line=LineString(((a[0]-v[0],a[1]-v[1]),
				(a[0]+v[0],a[1]+v[1])))
	else:
		raise ValueError(f"Unbekannter CGAL-Kantentyp: {kind}")
	if not line.is_valid:
		raise ValueError(f"Ungültiges CGAL-Liniensegment: "
			f"Typ={kind}, Start={a}, Ende={b}, "
			f"Länge={line.length:.12g} m")
	return line.intersection(window)


def _read_dual_lines(path,window,origin):
	ox,oy=origin
	lines=[]
	stats={"S":0,"R":0,"L":0,"clipped":0,"degenerate_S":0}
	with Path(path).open("r",encoding="utf-8") as source:
		for line_number,line in enumerate(source,1):
			if line_number%100000==0:
				print(f"CGAL: {line_number:,} Voronoi-Grenzstücke eingelesen",flush=True)
			fields=line.split()
			if len(fields)!=5 or fields[0] not in ("S","R","L"):
				raise ValueError(f"CGAL-Kantenformat ungültig, Zeile {line_number}")
			values=list(map(float,fields[1:]))
			if not all(math.isfinite(v) for v in values):
				raise ValueError(f"Nicht endliche CGAL-Koordinate, Zeile {line_number}")
			coords=((values[0]/SCALE+ox,values[1]/SCALE+oy),
				(values[2]/SCALE+ox,values[3]/SCALE+oy))
			try:
				section=_record_line(fields[0],coords,window)
			except ValueError as exc:
				raise ValueError(f"CGAL-Dualgrenze in Zeile {line_number}: "
					f"{line.strip()!r}: {exc}") from exc
			stats[fields[0]]+=1
			if section is None:
				stats["degenerate_S"]+=1
				continue
			for part in (section.geoms if hasattr(section,"geoms") else (section,)):
				if isinstance(part,LineString) and part.length>0:
					lines.append(part)
					stats["clipped"]+=1
	return lines,stats


def _polygon_candidates(lines,window):
	if not lines:
		raise ValueError("Keine CGAL-Voronoi-Kanten im Ausschnitt")
	print(f"CGAL: {len(lines):,} begrenzte Grenzstücke noding/union",flush=True)
	# Noding also handles the intersections with the clipping rectangle.
	boundaries=[window.boundary,*lines]
	noded=unary_union(boundaries)
	print("CGAL: Noding beendet, polygonize_full",flush=True)
	polygons,dangles,cuts,invalid=polygonize_full(noded)
	if not invalid.is_empty:
		raise ValueError("CGAL-Grenzen erzeugen ungültige Polygonringe")
	candidates=[poly for poly in polygons.geoms
		if poly.area>0 and window.covers(poly.representative_point())]
	if not candidates:
		raise ValueError("Keine geschlossenen CGAL-Voronoi-Zellen")
	total=union_all(candidates)
	gap=window.difference(total).area
	overlap=sum(poly.area for poly in candidates)-total.area
	tolerance=max(0.01,window.area*1e-8)
	if gap>tolerance or overlap>tolerance:
		raise ValueError(f"Voronoi-Debugflächen nicht deckungsgleich: "
			f"Lücken {gap:.3f} m², Überlappung {overlap:.3f} m²")
	return candidates,{"candidates":len(candidates),
		"dangles":len(dangles.geoms),"cuts":len(cuts.geoms),
		"gap_m2":gap,"overlap_m2":overlap}


def _assign(polygons,mask,owners,origin,*,mask_parts=None,batch_size=512,
		face_labels=None):
	"""Clip already-labelled complete faces to SIS in vectorized batches."""
	if batch_size<1:
		raise ValueError("batch_size muss >= 1 sein")
	if face_labels is None:
		raise ValueError("Eindeutige LINEAR_USE-Flächenzuordnung erforderlich")
	if len(face_labels)!=len(polygons):
		raise ValueError("Anzahl der Face-Labels stimmt nicht")
	if any(label not in set(owners.values()) for label in face_labels):
		raise ValueError("Unbekannte LINEAR_USE-edge_id")
	if mask_parts is None:
		mask_parts=list(mask.geoms) if hasattr(mask,"geoms") else [mask]
	mask_parts=[part for part in mask_parts if not part.is_empty and part.area>0]
	prepare(mask_parts)
	mask_tree=STRtree(mask_parts)
	mask_array=np.asarray(mask_parts,dtype=object)
	grouped={}
	intersections_calculated=0
	for offset in range(0,len(polygons),batch_size):
		batch=np.asarray(polygons[offset:offset+batch_size],dtype=object)
		matches=mask_tree.query(batch,predicate="intersects")
		if not matches.shape[1]:
			continue
		poly_indices,mask_indices=matches
		parts=vector_intersection(batch[poly_indices],mask_array[mask_indices])
		intersections_calculated+=len(parts)
		nonempty=(~vector_is_empty(parts)) & (vector_area(parts)>0)
		for poly_index,part in zip(poly_indices[nonempty],parts[nonempty]):
			owner=face_labels[offset+int(poly_index)]
			grouped.setdefault(owner,[]).extend(_polygonal(part))
	if not grouped:
		raise ValueError("Keine CGAL-Zellfläche schneidet die SIS-Straßenmaske")
	merged={owner:union_all(parts) for owner,parts in grouped.items()}
	for owner,geom in merged.items():
		if not geom.is_valid:
			raise ValueError(f"Ungültige CGAL/SIS-Vereinigung für {owner}")
	union=union_all(list(merged.values()))
	gap=mask.difference(union).area
	overlap=sum(geom.area for geom in merged.values())-union.area
	tolerance=max(0.01,mask.area*1e-7)
	if gap>tolerance or overlap>tolerance:
		raise ValueError(f"CGAL/SIS-Flächenbilanz: Lücke {gap:.3f} m², "
			f"Überlappung {overlap:.3f} m²")
	return merged,{"gap_m2":gap,"overlap_m2":overlap,
		"street_m2":mask.area,"assigned_m2":union.area,
		"intersections_calculated":intersections_calculated,
		"batch_size":batch_size,"mask_tile_parts":len(mask_parts)}


def _connected_components(geometry):
	"""Dissolve touching polygons; disconnected parts remain separate features.

	Boundary contact, including a single shared vertex, counts as touching.
	A group touching only at points may remain a MultiPolygon geometry.
	"""
	pieces=_polygonal(geometry)
	if len(pieces)<2:
		return pieces
	tree=STRtree(pieces)
	parent=list(range(len(pieces)))
	def find(i):
		while parent[i]!=i:
			parent[i]=parent[parent[i]]
			i=parent[i]
		return i
	for i,part in enumerate(pieces):
		for j in tree.query(part,predicate="intersects"):
			j=int(j)
			if j<=i:
				continue
			a,b=find(i),find(j)
			if a!=b:
				parent[b]=a
	groups={}
	for i,part in enumerate(pieces):
		groups.setdefault(find(i),[]).append(part)
	return [union_all(group) for group in groups.values()]

def _polygonal(geometry):
	"""Collect polygonal make_valid parts without fabricating buffered area."""
	if isinstance(geometry,Polygon):
		return [geometry] if not geometry.is_empty and geometry.area>0 else []
	if isinstance(geometry,MultiPolygon):
		return [p for p in geometry.geoms if not p.is_empty and p.area>0]
	if hasattr(geometry,"geoms"):
		return [p for g in geometry.geoms for p in _polygonal(g)]
	return []


def _export_wgs84_polygon(metric, to_wgs, to_metric, *, edge_id,
		tolerance_m2=0.01):
	"""Remove projection-degenerate details only after metric footprint QA.

	Do not compare the original metric polygon against a WGS84 roundtrip:
	EPSG:31256 -> EPSG:4326 -> EPSG:31256 introduces projection
	roundtrip displacement even if NO geometry was removed.
	"""
	if metric.is_empty or not metric.is_valid:
		raise ValueError(f"{edge_id}: metrische Ausgangsfläche ungültig")
	wgs=transform(to_wgs,metric)
	if wgs.is_valid and not wgs.is_empty:
		return wgs,None
	reason=explain_validity(wgs)
	if not reason.startswith("Too few points in geometry component"):
		raise ValueError(f"{edge_id}: GeoJSON-Transformation ungültig: {reason}")

	# Collapse only unrepresentable sub-millimetre details in the original
	# metric CRS. A changed topology is accepted solely when the absolute
	# *metric* symmetric-difference area stays within the original tolerance.
	for precision_m in (1e-7,1e-6,1e-5,1e-4,1e-3):
		candidate=set_precision(metric,precision_m,mode="valid_output")
		if candidate.is_empty or not candidate.is_valid or (
				not isinstance(candidate,(Polygon,MultiPolygon))):
			continue
		try:
			change_m2=metric.symmetric_difference(candidate).area
		except Exception as exc:
			raise ValueError(
				f"{edge_id}: metrische Flächentreue nicht nachweisbar: {exc}") from exc
		if not math.isfinite(change_m2) or change_m2>tolerance_m2:
			continue
		reprojected=transform(to_wgs,candidate)
		if reprojected.is_valid and not reprojected.is_empty:
			return reprojected,{"edge_id":edge_id,"reason":reason,
				"method":"metric_precision_cleanup_before_wgs84",
				"precision_m":precision_m,
				"symmetric_difference_m2":change_m2}
	raise ValueError(f"{edge_id}: WGS84-Degeneration ohne flächentreue "
		f"metrische Bereinigung (maximal {tolerance_m2:.6f} m²); {reason}")

def build(cache,aoi_path,manifest,sis_root,binary,out,*,timeout=900):
	if not math.isfinite(timeout) or timeout<=0:
		raise ValueError("Timeout muss positiv sein")
	out=Path(out)
	if out.exists() or out.is_symlink():
		raise FileExistsError(out)
	if not Path(binary).is_file():
		raise FileNotFoundError(f"CGAL-Binary fehlt: {binary}")
	aoi=load_aoi(aoi_path)
	window=box(*aoi.bounds)
	mask,mask_parts=_window_mask(manifest,sis_root,aoi_path,window)
	records=_source_records(cache)
	owners,origin=_noded_segments([(edge_id,line)
		for _object_id,edge_id,line in records],
		progress=lambda message:print(message,flush=True))
	frame=_frame(aoi,origin)
	ox,oy=origin
	bounds=[round((v-(ox if i%2==0 else oy))*SCALE)
		for i,v in enumerate(window.bounds)]
	payload="".join(_payload(owners,frame))
	out.parent.mkdir(parents=True,exist_ok=True)
	with tempfile.TemporaryDirectory(prefix="cgal-voronoi-",dir=out.parent) as temp:
		edges=Path(temp)/"dual.txt"
		command=[str(Path(binary).resolve()),"--edges",str(edges),
			"--bounds",*(str(v) for v in bounds)]
		try:
			proc=subprocess.run(command,input=payload,text=True,
				capture_output=True,timeout=timeout,check=False)
		except subprocess.TimeoutExpired as exc:
			raise RuntimeError("CGAL-Laufzeitlimit überschritten") from exc
		if proc.returncode:
			raise RuntimeError(f"CGAL-Dualexport fehlgeschlagen: {proc.stderr[-2000:]}")
		if not edges.is_file():
			raise RuntimeError("CGAL lieferte keine Dualgrenzen-Datei")
		lines,stats=_read_dual_lines(edges,window,origin)
		candidates,topology=_polygon_candidates(lines,window)
		# Match original source lines against FULL Voronoi candidates,
		# before clipping to SIS; do not invent a representative point.
		attribution=assign_by_intersections(candidates,records)
		to_wgs=Transformer.from_crs(31256,4326,always_xy=True).transform
		diagnostics=write_diagnostics(
			out,candidates,records,attribution,to_wgs)
		report=attribution["report"]
		print("LINEAR_USE-Flächenschnitt: "
			f"{report['lines_exactly_one_polygon']:,} eindeutige Linien, "
			f"{report['lines_multiple_polygons']:,} Mehrfachtreffer, "
			f"{report['lines_no_polygon']:,} ohne Fläche, "
			f"{report['polygons_conflicting_edge_ids']:,} edge_id-Konflikte, "
			f"{report['polygons_without_unambiguous_edge_id']:,} "
			"unzugeordnete Flächen",flush=True)
		if (attribution["multiple"] or attribution["missing"] or
				attribution["conflicts"] or attribution["unassigned"]):
			raise ValueError("LINEAR_USE-Flächenzuordnung ist nicht eindeutig. "
				"Vier GeoJSON-Diagnoselayer und Bericht gespeichert unter "
				f"{diagnostics['report']}. Kein SIS-Export freigegeben.")
		face_labels=attribution["labels"]
		groups,balance=_assign(candidates,mask,owners,origin,
			mask_parts=mask_parts,face_labels=face_labels)
		to_wgs=Transformer.from_crs(31256,4326,always_xy=True).transform
		to_metric=Transformer.from_crs(4326,31256,always_xy=True).transform
		features=[]
		repairs=[]
		for edge_id,geom in sorted(groups.items()):
			for connected in _connected_components(geom):
				converted,repair=_export_wgs84_polygon(connected,
					to_wgs,to_metric,edge_id=edge_id)
				if repair is not None:
					repairs.append(repair)
				features.append({"type":"Feature",
					"properties":{"edge_id":edge_id,"area_m2":connected.area,
						"method":"cgal_segment_voronoi","debug":True,
						"curve_linearization":"cgal_draw"},
					"geometry":mapping(converted)})
		collection={"type":"FeatureCollection","features":features,
			"metadata":{"schema":"cgal-original-line-intersections-sis-v1",
				"crs":"EPSG:4326","bbox_31256":list(window.bounds),
				"source_segments":len(owners),"dual_primitives":stats,
				"polygonization":topology,"balance":balance,
				"export_geometry_repairs":repairs,
				"experimental":True}}
		stage=Path(temp)/"result.geojson"
		stage.write_text(json.dumps(collection,ensure_ascii=False,
			separators=(",",":"),allow_nan=False)+"\n",encoding="utf-8")
		os.replace(stage,out)
	print(f"CGAL/SIS: {len(features)} räumlich zusammenhängende Teilflächen; {out}",flush=True)
	return len(features)

def main():
	p=argparse.ArgumentParser(description=__doc__)
	p.add_argument("--cache",type=Path,required=True)
	p.add_argument("--aoi",type=Path,required=True)
	p.add_argument("--sis-manifest",type=Path,required=True)
	p.add_argument("--sis-root",type=Path,required=True)
	p.add_argument("--binary",type=Path,required=True)
	p.add_argument("--out",type=Path,required=True)
	p.add_argument("--timeout",type=float,default=900)
	a=p.parse_args()
	build(a.cache,a.aoi,a.sis_manifest,a.sis_root,a.binary,a.out,
		timeout=a.timeout)


if __name__=="__main__":
	main()
