"""CGAL true segment-site Voronoi debug polygons intersected with verified SIS.

CGAL constructs the graph from ALL Wiener segments. Only its dual boundary
export is windowed; no tile-local or point-site Voronoi is substituted.
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
from shapely import union_all
from shapely.geometry import LineString, Polygon, box, mapping
from shapely.ops import polygonize_full, transform, unary_union
from shapely.strtree import STRtree
from shapely.wkb import loads

from scripts.cgal_segment_input import SCALE, _noded_segments
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
	for tile in manifest["tiles"]:
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
	return result


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
	# Noding also handles the intersections with the clipping rectangle.
	boundaries=[window.boundary,*lines]
	noded=unary_union(boundaries)
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


def _assign(polygons,mask,owners,origin):
	ox,oy=origin
	keys=sorted(owners)
	geoms=[LineString(((a[0]/SCALE+ox,a[1]/SCALE+oy),
		(b[0]/SCALE+ox,b[1]/SCALE+oy))) for a,b in keys]
	tree=STRtree(geoms)
	grouped={}
	for polygon in polygons:
		part=polygon.intersection(mask)
		if part.is_empty or part.area==0:
			continue
		# A Voronoi boundary encloses segment sites and endpoint point-sites;
		# attribute each dual face using its representative point.
		index=int(tree.nearest(polygon.representative_point()))
		owner=owners[keys[index]]
		grouped.setdefault(owner,[]).append(part)
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
		"street_m2":mask.area,"assigned_m2":union.area}


def build(cache,aoi_path,manifest,sis_root,binary,out,*,bbox=None,timeout=300):
	if not math.isfinite(timeout) or timeout<=0:
		raise ValueError("Timeout muss positiv sein")
	out=Path(out)
	if out.exists() or out.is_symlink():
		raise FileExistsError(out)
	if not Path(binary).is_file():
		raise FileNotFoundError(f"CGAL-Binary fehlt: {binary}")
	aoi=load_aoi(aoi_path)
	if bbox is None:
		cx,cy=aoi.centroid.coords[0]
		window=box(cx-250,cy-250,cx+250,cy+250).intersection(aoi)
	else:
		if not all(math.isfinite(v) for v in bbox):
			raise ValueError("Ungültige Debug-BBOX")
		window=box(*bbox).intersection(aoi)
	if window.is_empty or window.area<=0:
		raise ValueError("Debug-BBOX liegt außerhalb der AOI")
	if window.geom_type!="Polygon" or len(window.interiors):
		raise ValueError("Debug-Ausschnitt muss einfaches Polygon sein")
	print("CGAL: SIS-Maske und genodete Wiener Achsen einlesen",flush=True)
	mask=_window_mask(manifest,sis_root,aoi_path,window)
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
		command=[str(Path(binary).resolve()),"--edges",str(edges),
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
		print("CGAL: Grenzen beschneiden und polygonisieren",flush=True)
		lines,stats=_read_dual_lines(edges,box(*window.bounds),origin)
		candidates,topology=_polygon_candidates(lines,box(*window.bounds))
		print(f"CGAL: {len(candidates):,} Teilflächen mit SIS verschneiden",flush=True)
		groups,balance=_assign(candidates,mask,owners,origin)
		to_wgs=Transformer.from_crs(31256,4326,always_xy=True).transform
		features=[]
		for edge_id,geom in sorted(groups.items()):
			features.append({"type":"Feature",
				"properties":{"edge_id":edge_id,"area_m2":geom.area,
					"method":"cgal_segment_voronoi",
					"debug":True,"curve_linearization":"cgal_draw"},
				"geometry":mapping(transform(to_wgs,geom))})
		collection={"type":"FeatureCollection",
			"features":features,
			"metadata":{"schema":"cgal-segment-voronoi-sis-debug-v1",
				"crs":"EPSG:4326","bbox_31256":list(window.bounds),
				"source_segments":len(owners),"dual_primitives":stats,
				"polygonization":topology,"balance":balance,
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
	p.add_argument("--bbox",type=float,nargs=4,metavar=("XMIN","YMIN","XMAX","YMAX"))
	p.add_argument("--timeout",type=float,default=300)
	a=p.parse_args()
	build(a.cache,a.aoi,a.sis_manifest,a.sis_root,a.binary,a.out,
		bbox=a.bbox,timeout=a.timeout)


if __name__=="__main__":
	main()
