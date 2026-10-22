"""Final Wiener CGAL-area overlay with ALL SIS-Belagsflächen, by edge_id.

Use the existing finalized Vienna SIS WFS-derived RTree (not the small
SIS pilot), and the INTERNAL union of native CGAL Faces produced before
SIS by dissolve_cgal_preview. Preserve the existing debug output from
that earlier stage, unchanged. Keep only positive-area intersections,
retaining Polygon/MultiPolygon and the original edge_id. No SIS BELAG
or TYPE filtering. No geometry repair/ownership reassignment.

Streams the line-oriented dissolved GeoJSON without loading all Vienna
features into memory. Refuses incomplete SIS index and malformed
upstream results; writes the final GeoJSON atomically.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from urllib.parse import quote

from pyproj import Transformer
from shapely import make_valid,union_all
from shapely.geometry import Polygon,MultiPolygon,shape,mapping
from shapely.ops import transform
from shapely.validation import explain_validity

from scripts.sis_wien_source import mask as sis_mask


SCHEMA="cgal-native-faces-sis-belagsflaechen-wien-v2-checked-projection-repair"
SIS_SCHEMAS=frozenset(("sis-wien-index-v4","sis-wien-index-v5"))
# The source WFS geometries and inverse WGS84 <-> MGI/31256 transform
# can create sub-centimetre-wide boundary slivers on an exact boundary
# touch. Below 0.01 m² these are far below source-map precision.
SIS_MIN_INTERSECTION_AREA_M2=0.01


def _features(path):
	"""Read exactly our streamed pre-SIS FeatureCollection."""
	with Path(path).open("r",encoding="utf-8") as inp:
		if inp.readline().strip()!='{"type":"FeatureCollection","features":[':
			raise ValueError("SIS-Schnitt benötigt das zeilenweise CGAL-Dissolve-GeoJSON")
		metadata=None
		for number,line in enumerate(inp,2):
			raw=line.strip()
			if not raw:
				continue
			if raw.startswith('],"metadata":'):
				doc=json.loads('{"type":"FeatureCollection","features":[]'+raw[1:])
				metadata=doc.get("metadata")
				break
			try:
				feature=json.loads(raw[:-1] if raw.endswith(",") else raw)
			except json.JSONDecodeError as exc:
				raise ValueError(f"CGAL-Dissolve-Zeile {number}: ungültiges Feature") from exc
			if not isinstance(feature,dict) or feature.get("type")!="Feature":
				raise ValueError(f"CGAL-Dissolve-Zeile {number}: kein Feature")
			yield feature
		if not isinstance(metadata,dict):
			raise ValueError("CGAL-Dissolve-Ausgabe abgeschnitten (Metadata fehlt)")
		if not (str(metadata.get("schema","")).startswith(
				"cgal-original-edge-id-turn-use-hull-dissolve-")
				and metadata.get("dissolved_by")=="edge_id"):
			raise ValueError("Keine geprüfte finale CGAL-Dissolve-Eingabe")
		if inp.read().strip():
			raise ValueError("CGAL-Dissolve-Ausgabe enthält überzählige Daten")


def _validate_index(db):
	try:
		meta=dict(db.execute("SELECT key,value FROM metadata"))
		tables={name for (name,) in db.execute(
			"SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
	except sqlite3.Error as exc:
		raise ValueError("SIS-Wien-Index kann nicht gelesen werden") from exc
	if (meta.get("schema") not in SIS_SCHEMAS
			or meta.get("provider")!="SISBELAGOGD"
			or meta.get("crs")!="EPSG:31256"
			or not meta.get("sha256")):
		raise ValueError("SIS-Wien-Index unvollständig, veraltet oder falscher Provider")
	if not {"features","feature_index"}.issubset(tables):
		raise ValueError("SIS-Wien-Index ohne Features/RTree")
	if db.execute("SELECT COUNT(*) FROM features").fetchone()[0]==0:
		raise ValueError("SIS-Wien-Index ist leer")
	return meta


def _polygonal_parts(geom):
	if isinstance(geom,Polygon):
		return [geom] if not geom.is_empty else []
	if isinstance(geom,MultiPolygon):
		return [part for part in geom.geoms if not part.is_empty]
	if hasattr(geom,"geoms"):
		return [part for item in geom.geoms for part in _polygonal_parts(item)]
	return []


def _strip_projection_collapsed_holes(metric,wgs,to_metric):
	"""Discard only genuine metric holes that become non-rings in WGS84.

	For an otherwise valid EPSG:31256 Polygon, a near-zero-area
	interior ring can project to two distinct longitude/latitude
	coordinates. The invalid WGS84 ring then has no enclosed area,
	but make_valid drops its metres-long boundary. A blanket boundary
	Hausdorff threshold therefore rejects an almost identical *area*.

	Instead compare each source hole with its own projected ring.
	Only non-ring holes with a combined metric area <= 0.01 m² (or
	1e-6 of feature area) may be dropped, never an ordinary hole.
	All retained coordinate sequences are left exactly unchanged;
	any other invalidity must still use the strict existing path.
	"""
	source=(metric.geoms if isinstance(metric,MultiPolygon) else (metric,))
	projected=(wgs.geoms if isinstance(wgs,MultiPolygon) else (wgs,))
	if len(source)!=len(projected):
		return None
	budget=max(0.01,metric.area*1e-6)
	lost_area=0.
	discarded=0
	new_polys=[]
	for original,converted in zip(source,projected):
		if len(original.interiors)!=len(converted.interiors):
			return None
		interiors=[]
		for source_hole,converted_hole in zip(
				original.interiors,converted.interiors):
			coords=converted_hole.coords
			distinct=len(set(coords[:-1]))
			if distinct>=3:
				interiors.append(coords)
				continue
			# A collapsed WGS84 hole can only be removed when the
			# original (valid!) metric interior carried negligible area.
			metric_hole_area=Polygon(source_hole).area
			if metric_hole_area>budget-lost_area:
				return None
			lost_area+=metric_hole_area
			discarded+=1
		new_polys.append(Polygon(converted.exterior,interiors))
	if not discarded:
		return None
	candidate=new_polys[0] if len(new_polys)==1 else MultiPolygon(new_polys)
	if candidate.is_empty or not candidate.is_valid:
		return None
	verified=transform(to_metric,candidate)
	if verified.is_empty or not verified.is_valid:
		return None
	# The only intended topological change is filling the collapsed
	# holes. The other rings have identical WGS84 coordinates.
	area_shift=abs(verified.area-transform(to_metric,wgs).area)
	if area_shift>budget:
		return None
	boundary_shift=transform(to_metric,wgs).boundary.hausdorff_distance(
		verified.boundary)
	return candidate,{
		"repair":"remove_only_projection_collapsed_interior_rings",
		"repair_result_type":candidate.geom_type,
		"discarded_collapsed_holes":discarded,
		"discarded_metric_hole_area_m2":lost_area,
		"area_shift_m2":area_shift,
		"area_tolerance_m2":budget,
		"boundary_shift_m":boundary_shift,
		"boundary_shift_note":"Abweichung enthält bewusst entfernte flächenlose Innenringe; "
			"alle anderen Koordinaten unverändert",
	}


def _export_valid_wgs84(metric,to_metric,to_wgs,edge_id):
	"""Repair ONLY invalidity introduced by reprojection, with safeguards.

	Metric geometry is already a valid SIS intersection. We never
	change it or its edge_id. In exceptional cases floating-point
	round-trip makes the WGS84 geometry topologically invalid. Only
	a make_valid polygonal result demonstrably indistinguishable at
	the projected geometry precision is admissible. Never buffer(0)
	blindly or silently skip an edge_id.
	"""
	wgs=transform(to_wgs,metric)
	if isinstance(wgs,(Polygon,MultiPolygon)) and not wgs.is_empty and wgs.is_valid:
		return wgs,None
	if wgs.is_empty or not isinstance(wgs,(Polygon,MultiPolygon)):
		raise ValueError(f"{edge_id}: SIS->WGS84 ist leer oder nicht polygonal")
	invalidity=explain_validity(wgs)
	if invalidity.startswith("Too few points in geometry component"):
		collapsed=_strip_projection_collapsed_holes(metric,wgs,to_metric)
		if collapsed is not None:
			candidate,event=collapsed
			event["edge_id"]=edge_id
			event["original_wgs84_invalidity"]=invalidity
			return candidate,event
	try:
		repaired=make_valid(wgs)
		pieces=_polygonal_parts(repaired)
		if not pieces:
			raise ValueError("make_valid liefert keine polygonalen Bestandteile")
		candidate=union_all(pieces)
		if (not isinstance(candidate,(Polygon,MultiPolygon))
				or candidate.is_empty or not candidate.is_valid):
			raise ValueError("make_valid-Polygone ergeben keine gültige Fläche")
		# Both candidates are projected BACK from the identical WGS84
		# coordinates; this isolates the tiny repair from the ordinary
		# curved datum-transformation difference to the source Polygon.
		roundtrip=transform(to_metric,wgs)
		verified=transform(to_metric,candidate)
		if not verified.is_valid or verified.is_empty:
			raise ValueError("Reparierte Fläche ist in EPSG:31256 ungültig")
		area_shift=abs(verified.area-roundtrip.area)
		# 0.01 m² absolute and 1e-6 relative to the clipped area.
		area_tolerance=max(0.01,metric.area*1e-6)
		if area_shift>area_tolerance:
			raise ValueError(
				f"Flächendifferenz nach Reparatur {area_shift:.6g} m² "
				f"größer als Toleranz {area_tolerance:.6g} m²")
		# GEOS can validate a polygon after a wholesale rearrangement.
		# Demand its boundary remains within 2 cm of the ORIGINAL
		# (WGS84 -> metric roundtrip) rings.
		boundary_distance=roundtrip.boundary.hausdorff_distance(
			verified.boundary)
		if boundary_distance>0.02:
			raise ValueError(
				f"Randabweichung nach Reparatur {boundary_distance:.6g} m "
				"überschreitet 0.02 m")
		event={
			"edge_id":edge_id,
			"original_wgs84_invalidity":invalidity,
			"repair":"shapely.make_valid / nur polygonale Bestandteile",
			"repair_result_type":candidate.geom_type,
			"area_shift_m2":area_shift,
			"area_tolerance_m2":area_tolerance,
			"boundary_shift_m":boundary_distance,
		}
		return candidate,event
	except Exception as exc:
		raise ValueError(
			f"{edge_id}: ungültiger WGS84-SIS-Polygonschnitt "
			f"({invalidity}); kontrollierte Reparatur abgelehnt: {exc}"
		) from exc


def _clip_feature(feature,db,to_metric,to_wgs,stats):
	props=feature.get("properties")
	if not isinstance(props,dict) or not isinstance(props.get("edge_id"),str) or not props["edge_id"]:
		raise ValueError("CGAL-Dissolve-Feature ohne originale edge_id")
	if props.get("sis_clipped") is not False:
		raise ValueError(f"{props['edge_id']}: SIS-Schnitt wurde bereits ausgeführt")
	geom=shape(feature.get("geometry"))
	if not isinstance(geom,(Polygon,MultiPolygon)) or geom.is_empty or not geom.is_valid:
		raise ValueError(f"{props['edge_id']}: ungültige polygonale CGAL-Eingabe")
	metric=transform(to_metric,geom)
	if not isinstance(metric,(Polygon,MultiPolygon)) or metric.is_empty or not metric.is_valid or metric.area<=0:
		raise ValueError(f"{props['edge_id']}: ungültige metrische CGAL-Eingabe")
	stats["pre_sis_area_sum_m2"]+=metric.area
	# Same proven SIS WFS-index RTree/geometry union used by the
	# existing SIS-V2 street mask, including ALL BELAG and TYPE values.
	clip=sis_mask(db,metric)
	if clip is None or clip.is_empty or clip.area<=SIS_MIN_INTERSECTION_AREA_M2:
		stats["without_sis_overlap"]+=1
		return None
	if not isinstance(clip,(Polygon,MultiPolygon)) or not clip.is_valid:
		raise ValueError(f"{props['edge_id']}: ungültiger SIS-Polygonschnitt")
	# Guard area against accidental expansion / wrong mask.
	if clip.difference(metric).area>max(.01,metric.area*1e-9):
		raise ValueError(f"{props['edge_id']}: SIS-Ergebnis überschreitet ursprüngliche CGAL-Fläche")
	wgs,repair=_export_valid_wgs84(clip,to_metric,to_wgs,props["edge_id"])
	if repair is not None:
		stats["wgs84_repaired_features"]+=1
		stats["wgs84_repair_area_shift_m2"]+=repair["area_shift_m2"]
		if repair["repair"]=="remove_only_projection_collapsed_interior_rings":
			stats["wgs84_collapsed_holes_removed"]+=repair["discarded_collapsed_holes"]
			stats["wgs84_collapsed_hole_area_m2"]+=repair["discarded_metric_hole_area_m2"]
	outprops=dict(props)
	outprops.update({
		"pre_sis_area_m2":metric.area,
		"area_m2":clip.area,
		"sis_clipped":True,
		"sis_provider":"SISBELAGOGD",
		"sis_mask":"all_belags_all_types",
		"sis_min_area_m2":SIS_MIN_INTERSECTION_AREA_M2,
		"wgs84_projection_repaired":repair is not None,
		"wgs84_repair_method":repair["repair"] if repair is not None else None,
	})
	stats["features_with_sis_overlap"]+=1
	stats["sis_overlap_area_sum_m2"]+=clip.area
	if isinstance(clip,MultiPolygon):
		stats["sis_multipolygon_features"]+=1
	return {"type":"Feature","properties":outprops,"geometry":mapping(wgs)}


def clip(pre_sis,sis_db,out,*,replace_existing=False,progress=None):
	pre_sis,sis_db,out=map(Path,(pre_sis,sis_db,out))
	if not pre_sis.is_file() or pre_sis.is_symlink():
		raise FileNotFoundError(f"CGAL-Dissolve-Eingabe fehlt: {pre_sis}")
	if not sis_db.is_file() or sis_db.is_symlink():
		raise FileNotFoundError(
			f"Wiener SIS-Index fehlt: {sis_db}. Zuerst "
			"bash code/scripts/run-sis-v2-wien.sh ausführen.")
	if out.is_symlink():
		raise ValueError(f"SIS-Ausgabe darf kein Symlink sein: {out}")
	if out.exists() and not replace_existing:
		raise FileExistsError(out)
	out.parent.mkdir(parents=True,exist_ok=True)
	if len({str(p.resolve()) for p in (pre_sis,sis_db,out)})!=3:
		raise ValueError("SIS-Eingaben und Ausgabe müssen verschieden sein")
	to_metric=Transformer.from_crs(4326,31256,always_xy=True).transform
	to_wgs=Transformer.from_crs(31256,4326,always_xy=True).transform
	stats=Counter()
	uri="file:"+quote(str(sis_db.resolve()),safe="/")+"?mode=ro"
	with sqlite3.connect(uri,uri=True) as db:
		meta=_validate_index(db)
		with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",
				dir=out.parent,prefix=out.name+".",suffix=".tmp",
				delete=False) as writer:
			stage=Path(writer.name)
			try:
				writer.write('{"type":"FeatureCollection","features":[\n')
				first=True
				for feature in _features(pre_sis):
					stats["pre_sis_features"]+=1
					clipped=_clip_feature(feature,db,to_metric,to_wgs,stats)
					if clipped is not None:
						if not first:
							writer.write(",\n")
						json.dump(clipped,writer,ensure_ascii=False,
							separators=(",",":"),allow_nan=False)
						first=False
					if progress and stats["pre_sis_features"]%1000==0:
						progress(
							f"SIS-Verschnitt: {stats['pre_sis_features']:,} "
							f"edge_ids, {stats['features_with_sis_overlap']:,} mit SIS-Fläche")
				writer.write('\n],"metadata":')
				json.dump({
					"schema":SCHEMA,
					"crs":"EPSG:4326",
					"metric_crs":"EPSG:31256",
					"sis_provider":"SISBELAGOGD",
					"sis_schema":meta["schema"],
					"sis_sha256":meta["sha256"],
					"sis_mask":"all_belags_all_types",
					"minimum_intersection_area_m2":SIS_MIN_INTERSECTION_AREA_M2,
					"wgs84_repair_method":"targeted_collapsed_tiny_holes_or_strict_make_valid",
					"debug_stage":"after_turn_use_and_250m2_before_sis",
					"pre_sis_intermediate_not_published":True,
					"statistics":dict(stats),
					"preview_based":True,
				},writer,ensure_ascii=False,separators=(",",":"),
					allow_nan=False)
				writer.write("}\n")
				writer.flush()
				os.replace(stage,out)
			finally:
				stage.unlink(missing_ok=True)
	print(f"SIS-Verschnitt: {stats['pre_sis_features']:,} CGAL-edge_ids, "
		f"{stats['features_with_sis_overlap']:,} SIS-Flächen, "
		f"{stats['without_sis_overlap']:,} ohne Überdeckung, "
		f"{stats['sis_multipolygon_features']:,} MultiPolygone, "
		f"{stats['wgs84_repaired_features']:,} konservative WGS84-Korrekturen, "
		f"{stats['wgs84_collapsed_holes_removed']:,} kollabierte Kleinst-Innenlöcher; "
		f"Ausgabe: {out}",flush=True)
	return dict(stats)


def main():
	p=argparse.ArgumentParser(description=__doc__)
	p.add_argument("--pre-sis",required=True,type=Path)
	p.add_argument("--sis-db",required=True,type=Path)
	p.add_argument("--out",required=True,type=Path)
	p.add_argument("--replace-existing",action="store_true")
	a=p.parse_args()
	clip(a.pre_sis,a.sis_db,a.out,replace_existing=a.replace_existing,
		progress=lambda message:print(message,flush=True))


if __name__=="__main__":
	main()
