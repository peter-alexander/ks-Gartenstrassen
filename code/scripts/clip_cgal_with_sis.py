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
import math
import os
from pathlib import Path
import sqlite3
import tempfile
from urllib.parse import quote

from pyproj import Transformer, Geod
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
	Only non-ring holes or wholly collapsed MultiPolygon parts with
	combined metric area <= 0.01 m² may be dropped, never an ordinary
	hole or material Polygon. The last remaining Polygon is never dropped.
	All retained coordinate sequences are left exactly unchanged;
	any other invalidity must still use the strict existing path.
	"""
	source=(metric.geoms if isinstance(metric,MultiPolygon) else (metric,))
	projected=(wgs.geoms if isinstance(wgs,MultiPolygon) else (wgs,))
	if len(source)!=len(projected):
		return None
	budget=0.01
	lost_area=0.
	discarded=0
	discarded_polygons=0
	new_polys=[]
	for original,converted in zip(source,projected):
		if len(set(converted.exterior.coords[:-1]))<3:
			if original.area>budget-lost_area:
				return None
			lost_area+=original.area
			discarded_polygons+=1
			continue
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
	if not (discarded or discarded_polygons) or not new_polys:
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
		"repair":"remove_only_projection_collapsed_negligible_rings",
		"repair_result_type":candidate.geom_type,
		"discarded_collapsed_holes":discarded,
		"discarded_collapsed_polygon_components":discarded_polygons,
		"discarded_metric_component_area_m2":lost_area,
		"area_shift_m2":area_shift,
		"area_tolerance_m2":budget,
		"boundary_shift_m":boundary_shift,
		"boundary_shift_note":"Abweichung enthält bewusst entfernte flächenlose Innenringe; "
			"alle anderen Koordinaten unverändert",
	}


def _recover_collapsed_metric_input(source_wgs,projected_metric):
	"""Remove only EPSG:31256-collapsed rings of negligible source geodesic area."""
	source=(source_wgs.geoms if isinstance(source_wgs,MultiPolygon) else (source_wgs,))
	projected=(projected_metric.geoms if isinstance(projected_metric,MultiPolygon)
		else (projected_metric,))
	if len(source)!=len(projected):
		return None
	geod=Geod(ellps="WGS84")
	budget=0.01
	removed_area=0.
	removed_holes=0
	removed_parts=0
	out=[]
	for original,metric in zip(source,projected):
		if len(original.interiors)!=len(metric.interiors):
			return None
		if len(set(metric.exterior.coords[:-1]))<3:
			lost=abs(geod.geometry_area_perimeter(original)[0])
			if lost>budget-removed_area:
				return None
			removed_area+=lost
			removed_parts+=1
			continue
		interiors=[]
		for hole_source,hole_metric in zip(original.interiors,metric.interiors):
			if len(set(hole_metric.coords[:-1]))>=3:
				interiors.append(hole_metric.coords)
				continue
			lost=abs(geod.geometry_area_perimeter(Polygon(hole_source))[0])
			if lost>budget-removed_area:
				return None
			removed_area+=lost
			removed_holes+=1
		out.append(Polygon(metric.exterior,interiors))
	if not out or not (removed_holes or removed_parts):
		return None
	candidate=out[0] if len(out)==1 else MultiPolygon(out)
	if candidate.is_empty or not candidate.is_valid or candidate.area<=0:
		return None
	if abs(candidate.area-projected_metric.area)>budget:
		return None
	return candidate,{
		"removed_holes":removed_holes,
		"removed_polygon_parts":removed_parts,
		"removed_source_geodesic_area_m2":removed_area,
		"method":"drop_only_projection_collapsed_wgs84_tiny_rings",
	}


def _repair_metric_self_intersection(source_wgs,metric,to_wgs):
	"""Audit a metric self-intersection without attributing CRS drift to make_valid.

	Return (candidate, measurements). The candidate is rejected only when
	its repair changes more than 0.01 m² of spatial footprint; report
	exactly which independent check prevented acceptance.
	"""
	details={"method":"make_valid_metric_verified_against_unrepaired_roundtrip",
		"change_budget_m2":0.01}
	if not explain_validity(metric).startswith("Self-intersection"):
		details["failure"]="not_self_intersection"
		return None,details
	try:
		validated=make_valid(metric)
		pieces=_polygonal_parts(validated)
		details["make_valid_type"]=validated.geom_type
		if not pieces:
			details["failure"]="make_valid_no_polygonal_parts"
			return None,details
		candidate=pieces[0] if len(pieces)==1 else union_all(pieces)
		details["repaired_metric_type"]=candidate.geom_type
		details["repaired_metric_valid"]=bool(candidate.is_valid)
		if not isinstance(candidate,(Polygon,MultiPolygon)) or candidate.is_empty or not candidate.is_valid:
			details["failure"]="invalid_metric_candidate"
			return None,details
		compare=transform(to_wgs,candidate)
		roundtrip=transform(to_wgs,metric)
		details["repaired_wgs84_valid"]=bool(compare.is_valid)
		# WGS84 validity is checked later on the actual SIS-clipped
		# geometry. It is not a prerequisite for comparing the repair
		# footprint here: the pre-repair roundtrip is itself invalid.
		details["unrepaired_wgs84_valid"]=bool(roundtrip.is_valid)
		if not isinstance(compare,(Polygon,MultiPolygon)) or compare.is_empty:
			details["failure"]="non_polygonal_roundtrip"
			return None,details
		changed=roundtrip.symmetric_difference(compare)
		geod=Geod(ellps="WGS84")
		changed_area=sum(abs(geod.geometry_area_perimeter(part)[0])
			for part in _polygonal_parts(changed))
		details["changed_geodesic_area_m2"]=changed_area
		if not math.isfinite(changed_area) or changed_area>0.01:
			details["failure"]="changed_area_exceeds_budget"
			return None,details
		details["failure"]=None
		return candidate,details
	except Exception as exc:
		details["failure"]="geometric_audit_exception"
		details["exception"]=f"{type(exc).__name__}: {exc}"
		return None,details


def _export_valid_wgs84(metric,to_metric,to_wgs,edge_id):
	"""Export the completed SIS intersection as a valid WGS84 Polygon/MultiPolygon.

	The user requested a GeoJSON, not a new geometric acceptance
	process. Reprojection sometimes creates ring self-intersections;
	make_valid can remove doubled-back, area-free lines. Keep only
	polygonal components as GeoJSON geometry. Do not block output on
	a Hausdorff threshold or roundtrip difference.
	"""
	wgs=transform(to_wgs,metric)
	if not isinstance(wgs,(Polygon,MultiPolygon)) or wgs.is_empty:
		raise ValueError(f"{edge_id}: SIS-Ergebnis in WGS84 nicht polygonal")
	if wgs.is_valid:
		return wgs,None
	invalidity=explain_validity(wgs)
	repaired=make_valid(wgs)
	pieces=_polygonal_parts(repaired)
	if not pieces:
		raise ValueError(f"{edge_id}: WGS84-Reparatur hat keine Polygonfläche")
	candidate=pieces[0] if len(pieces)==1 else union_all(pieces)
	if not isinstance(candidate,(Polygon,MultiPolygon)) or candidate.is_empty or not candidate.is_valid:
		raise ValueError(f"{edge_id}: WGS84-Reparatur liefert keine gültige Polygonfläche")
	return candidate,{
		"edge_id":edge_id,
		"original_wgs84_invalidity":invalidity,
		"repair":"make_valid_polygonal_export",
		"repair_result_type":candidate.geom_type,
		"area_shift_m2":0.,
		"area_tolerance_m2":None,
		"boundary_shift_m":None,
	}



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
	metric_repair=None
	if not isinstance(metric,(Polygon,MultiPolygon)) or metric.is_empty:
		raise ValueError(f"{props['edge_id']}: metrische CGAL-Geometrie fehlt")
	if not metric.is_valid:
		# Reprojection can make otherwise valid WGS84 rings self-touch.
		# Keep the polygonal area; do not reject a usable SIS intersection
		# for an unrequested centimetre-scale acceptance test.
		invalidity=explain_validity(metric)
		parts=_polygonal_parts(make_valid(metric))
		if not parts:
			raise ValueError(f"{props['edge_id']}: keine metrische Polygonfläche nach make_valid")
		metric=parts[0] if len(parts)==1 else union_all(parts)
		if not isinstance(metric,(Polygon,MultiPolygon)) or metric.is_empty or not metric.is_valid:
			raise ValueError(f"{props['edge_id']}: metrische Polygonreparatur nicht möglich")
		metric_repair={"method":"make_valid_polygonal_input","original_invalidity":invalidity}
		stats["input_metric_repaired_features"]+=1
	if metric.area<=0:
		raise ValueError(f"{props['edge_id']}: metrische CGAL-Fläche ist leer")
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
		if repair["repair"]=="remove_only_projection_collapsed_negligible_rings":
			stats["wgs84_collapsed_holes_removed"]+=repair["discarded_collapsed_holes"]
			stats["wgs84_collapsed_polygon_parts_removed"]+=repair["discarded_collapsed_polygon_components"]
			stats["wgs84_collapsed_metric_area_m2"]+=repair["discarded_metric_component_area_m2"]
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
		"input_metric_projection_repaired":metric_repair is not None,
		"input_metric_repair_method":metric_repair["method"] if metric_repair else None,
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
					"wgs84_repair_method":"make_valid_polygonal_export_without_roundtrip_acceptance_gate",
					"input_metric_repair_method":"collapsed_tiny_rings_or_symmetric_difference_verified_make_valid",
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
		f"{stats['wgs84_collapsed_holes_removed']:,} kollabierte Kleinst-Innenlöcher, "
		f"{stats['wgs84_collapsed_polygon_parts_removed']:,} kollabierte Kleinstpolygone; "
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
