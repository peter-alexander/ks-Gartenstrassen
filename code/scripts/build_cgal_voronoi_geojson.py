"""CGAL true segment-site Voronoi debug polygons intersected with verified SIS.

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
from time import perf_counter

from pyproj import Transformer
import numpy as np
from shapely import intersection as vector_intersection, area as vector_area, is_empty as vector_is_empty, prepare, union_all, make_valid
from shapely.geometry import LineString, Polygon, MultiPolygon, box, mapping
from shapely.ops import polygonize_full, transform, unary_union
from shapely.strtree import STRtree
from shapely.wkb import loads
from shapely.validation import explain_validity

from scripts.cgal_segment_input import SCALE, _noded_segments
from scripts.cgal_site_audit import inspect_sites_file
from scripts.cgal_face_sites import classify_polygon_generators_file
from scripts.wienwide_grid import checksum, load_aoi, read_manifest
from scripts.wienwide_street import load_street_tile


def _axes(cache):
	with sqlite3.connect(f"file:{Path(cache).resolve()}?mode=ro",uri=True) as db:
		rows=db.execute("SELECT edge_id,wkb FROM edge_axes ORDER BY edge_id").fetchall()
	if not rows:
		raise ValueError("Keine LINEAR_USE-Achsen")
	return [(edge_id,loads(blob)) for edge_id,blob in rows]


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
	"""Batch STRtree and GEOS intersection, retaining full area/overlap QA."""
	if batch_size<1:
		raise ValueError("batch_size muss >= 1 sein")
	if face_labels is not None and len(face_labels)!=len(polygons):
		raise ValueError("Anzahl der CGAL-Face-Labels stimmt nicht")
	if face_labels is not None and any(
		label is not None and label not in set(owners.values())
		for label in face_labels):
		raise ValueError("Unbekannte CGAL-Face-edge_id")
	ox,oy=origin
	keys=sorted(owners)
	geoms=[LineString(((a[0]/SCALE+ox,a[1]/SCALE+oy),
		(b[0]/SCALE+ox,b[1]/SCALE+oy))) for a,b in keys]
	tree=STRtree(geoms)
	# Keep the verified SIS tile cores separate for the spatial overlay.
	# Merging them into city-wide connected components produces extremely
	# complex geometries: spatial predicates and intersections then take hours.
	# Tile cores are disjoint in area; the union is still used for QA.
	if mask_parts is None:
		mask_parts=list(mask.geoms) if hasattr(mask,"geoms") else [mask]
	mask_parts=[part for part in mask_parts if not part.is_empty and part.area>0]
	prepare(mask_parts)
	mask_tree=STRtree(mask_parts)
	mask_array=np.asarray(mask_parts,dtype=object)
	print(f"CGAL: {len(mask_parts):,} SIS-Teilflächen räumlich indiziert; "
		f"vektorisierter Verschnitt in Blöcken zu {batch_size}",flush=True)
	grouped={}
	started=perf_counter()
	query_seconds=0.
	intersection_seconds=0.
	attribution_seconds=0.
	candidates_checked=0
	intersections_calculated=0
	assigned_polygons=0
	direct_components=0
	fallback_components=0
	total=len(polygons)
	for offset in range(0,total,batch_size):
		# Both STRtree.query and shapely.intersection are vectorized C/GEOS
		# calls. At most one batch of temporary intersections stays in RAM.
		batch=np.asarray(polygons[offset:offset+batch_size],dtype=object)
		t0=perf_counter()
		matches=mask_tree.query(batch,predicate="intersects")
		query_seconds+=perf_counter()-t0
		if matches.shape[1]:
			poly_indices=matches[0]
			mask_indices=matches[1]
			candidates_checked+=len(poly_indices)
			t0=perf_counter()
			parts=vector_intersection(batch[poly_indices],
				mask_array[mask_indices])
			intersections_calculated+=len(poly_indices)
			nonempty=(~vector_is_empty(parts)) & (vector_area(parts)>0)
			parts=parts[nonempty]
			surviving_indices=poly_indices[nonempty]
			intersection_seconds+=perf_counter()-t0
			if len(parts):
				# Attribute each *SIS-clipped polygon component*, not the
				# uncut CGAL polygon. A CGAL polygon can intersect multiple
				# disconnected SIS pieces near entirely different sites.
				# This is still a nearest-site approximation, not a CGAL
				# face/site identity export. The independent QA remains needed.
				t0=perf_counter()
				component_geometries=[]
				component_labels=[]
				for part,poly_index in zip(parts,surviving_indices):
					components=_polygonal(part)
					component_geometries.extend(components)
					label=(face_labels[offset+int(poly_index)]
						if face_labels is not None else None)
					component_labels.extend([label]*len(components))
				fallback_indices=[i for i,label in enumerate(component_labels)
					if label is None]
				fallback_owners={}
				if fallback_indices:
					representatives=np.asarray(
						[component_geometries[i].representative_point()
							for i in fallback_indices],dtype=object)
					nearest=tree.nearest(representatives)
					fallback_owners={i:owners[keys[int(j)]]
						for i,j in zip(fallback_indices,nearest)}
				for j,part in enumerate(component_geometries):
					owner=component_labels[j]
					if owner is None:
						owner=fallback_owners[j]
						fallback_components+=1
					else:
						direct_components+=1
					grouped.setdefault(owner,[]).append(part)
				assigned_polygons+=len(np.unique(surviving_indices))
				attribution_seconds+=perf_counter()-t0
		completed=min(offset+batch_size,total)
		if completed%10240<batch_size or completed==total:
			elapsed=perf_counter()-started
			print(f"CGAL: SIS-Verschnitt {completed:,}/{total:,} "
				f"({100*completed/total:.1f} %), {elapsed:.1f} s; "
				f"Kandidaten {candidates_checked:,}, Schnitte "
				f"{intersections_calculated:,}, zugeordnete Flächen "
				f"{assigned_polygons:,}; Index {query_seconds:.1f} s, "
				f"Schnitt {intersection_seconds:.1f} s, "
				f"Achse {attribution_seconds:.1f} s",flush=True)
	print(f"CGAL: SIS-Verschnitt fertig nach {perf_counter()-started:.1f} s; "
		f"{intersections_calculated:,} Schnittoperationen",flush=True)
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
		"batch_size":batch_size,
		"mask_tile_parts":len(mask_parts),
		"direct_site_components":direct_components,
		"fallback_components":fallback_components}



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
	"""Repair only degenerate projection rings proven to preserve footprint."""
	wgs=transform(to_wgs,metric)
	if wgs.is_valid and not wgs.is_empty:
		return wgs, None
	reason=explain_validity(wgs)
	if not reason.startswith("Too few points in geometry component"):
		raise ValueError(f"{edge_id}: GeoJSON-Transformation ungültig: {reason}")
	candidate=make_valid(wgs)
	parts=_polygonal(candidate)
	if not parts:
		raise ValueError(f"{edge_id}: Transformation ohne polygonale Fläche: {reason}")
	repaired=union_all(parts)
	if not repaired.is_valid or repaired.is_empty:
		raise ValueError(f"{edge_id}: make_valid lieferte ungültige Fläche")
	roundtrip=transform(to_metric,repaired)
	if not roundtrip.is_valid:
		raise ValueError(f"{edge_id}: reparierte Fläche nach Rückprojektion ungültig")
	try:
		symdiff=metric.symmetric_difference(roundtrip).area
	except Exception as exc:
		raise ValueError(f"{edge_id}: Flächentreue nicht nachweisbar: {exc}") from exc
	if symdiff>tolerance_m2:
		raise ValueError(f"{edge_id}: make_valid verändert Fläche um "
			f"{symdiff:.9f} m² (zulässig {tolerance_m2:.9f} m²)")
	return repaired, {"edge_id":edge_id,"reason":reason,
		"method":"make_valid_polygonal_area_verified",
		"symmetric_difference_m2":symdiff}

def build(cache,aoi_path,manifest,sis_root,binary,out,*,timeout=900):
	if not math.isfinite(timeout) or timeout<=0:
		raise ValueError("Timeout muss positiv sein")
	out=Path(out)
	if out.exists() or out.is_symlink():
		raise FileExistsError(out)
	if not Path(binary).is_file():
		raise FileNotFoundError(f"CGAL-Binary fehlt: {binary}")
	aoi=load_aoi(aoi_path)
	# The Voronoi is constructed and polygonized for all Vienna.
	# Its bounding rectangle closes open dual edges; the final
	# geometries are clipped to the actual AOI and SIS street mask.
	window=box(*aoi.bounds)
	print(f"CGAL: ganz Wien, Begrenzungsrechteck {window.bounds}",flush=True)
	print("CGAL: SIS-Maske und genodete Wiener Achsen einlesen",flush=True)
	mask,mask_parts=_window_mask(manifest,sis_root,aoi_path,window)
	owners,origin=_noded_segments(_axes(cache),
		progress=lambda message:print(message,flush=True))
	frame=_frame(aoi,origin)
	ox,oy=origin
	bounds=[round((v-(ox if i%2==0 else oy))*SCALE)
		for i,v in enumerate(window.bounds)]
	# Bounding box (not AOI outline) is sufficient for the native exporter;
	# the mask remains the exact AOI/SIS intersection.
	payload="".join(_payload(owners,frame))
	out.parent.mkdir(parents=True,exist_ok=True)
	with tempfile.TemporaryDirectory(prefix="cgal-voronoi-",dir=out.parent) as temp:
		edges=Path(temp)/"dual.txt"
		sites=Path(temp)/"sites.txt"
		command=[str(Path(binary).resolve()),"--edges",str(edges),
			"--sites",str(sites),
			"--bounds",*(str(v) for v in bounds)]
		print(f"CGAL: {len(owners):,} Segmente konstruieren; Dualgrenzen exportieren",
			flush=True)
		try:
			proc=subprocess.run(command,input=payload,text=True,
				capture_output=True,timeout=timeout,check=False)
		except subprocess.TimeoutExpired as exc:
			raise RuntimeError("CGAL-Laufzeitlimit überschritten") from exc
		if proc.returncode:
			raise RuntimeError(f"CGAL-Dualexport fehlgeschlagen: {proc.stderr[-2000:]}")
		if not edges.is_file():
			raise RuntimeError("CGAL lieferte keine Dualgrenzen-Datei")
		if not sites.is_file():
			raise RuntimeError("CGAL lieferte keine Site-Datei")
		site_stats=inspect_sites_file(sites,owners)
		print("CGAL-Sites: "+json.dumps(site_stats,ensure_ascii=False),flush=True)
		print("CGAL: Grenzen beschneiden und polygonisieren",flush=True)
		lines,stats=_read_dual_lines(edges,box(*window.bounds),origin)
		candidates,topology=_polygon_candidates(lines,box(*window.bounds))
		face_labels,face_stats=classify_polygon_generators_file(
			candidates,sites,owners,origin,SCALE)
		print("CGAL-Zellgeneratoren: "
			+json.dumps(face_stats,ensure_ascii=False),flush=True)
		print(f"CGAL: {len(candidates):,} Teilflächen mit SIS verschneiden",flush=True)
		groups,balance=_assign(candidates,mask,owners,origin,
			mask_parts=mask_parts,face_labels=face_labels)
		to_wgs=Transformer.from_crs(31256,4326,always_xy=True).transform
		to_metric=Transformer.from_crs(4326,31256,always_xy=True).transform
		features=[]
		repairs=[]
		for edge_id,geom in sorted(groups.items()):
			converted,repair=_export_wgs84_polygon(geom,to_wgs,to_metric,
				edge_id=edge_id)
			if repair is not None:
				repairs.append(repair)
			features.append({"type":"Feature",
				"properties":{"edge_id":edge_id,"area_m2":geom.area,
					"method":"cgal_segment_voronoi",
					"debug":True,"curve_linearization":"cgal_draw"},
				"geometry":mapping(converted)})
		print(f"GeoJSON-Export: {len(repairs)} flächentreu reparierte "
			"degenerierte Ringe",flush=True)
		collection={"type":"FeatureCollection",
			"features":features,
			"metadata":{"schema":"cgal-segment-voronoi-sis-debug-v1",
				"crs":"EPSG:4326","bbox_31256":list(window.bounds),
				"source_segments":len(owners),"dual_primitives":stats,
				"graph_sites":site_stats,
				"face_site_diagnostic":face_stats,
				"polygonization":topology,"balance":balance,
				"export_geometry_repairs":repairs,
				"experimental":True,
				"note":"CGAL-curve tessellation and cell ownership require "
					"independent geometric acceptance tests."}}
		stage=Path(temp)/"result.geojson"
		stage.write_text(json.dumps(collection,ensure_ascii=False,
			separators=(",",":"),allow_nan=False)+"\n",encoding="utf-8")
		os.replace(stage,out)
	print(f"CGAL-Debug: {len(features)} Straßenachsen; {out}",flush=True)
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
