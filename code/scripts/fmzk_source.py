"""Gemeinsamer, rein lesender FMZK-Adapter für unabhängige Analyse-Module.

Die Quelle ist das bereits extrahierte lokale GeoPackage (EPSG:31256).
Die Funktionen enthalten keine Logik zur Straßenraum-Klassifikation.
"""
import json
import math
from pathlib import Path
import sqlite3
from urllib.parse import quote

from shapely import make_valid
from shapely.geometry import Polygon, MultiPolygon
from shapely.validation import explain_validity

from scripts.analyze_gpkg import decode_gpkg_geometry, polygonal_part
from scripts.extract_fmzk import gpkg_info, parse_bbox, projected_clip

# Fachliche Boden-Grünklassen der aktuellen FMZK-Auswertung.
FMZK_GROUND_GREEN_CODES = frozenset((58, 69))
NO_AREA_EVENT = "ausgeschlossen_ohne_flaeche"
REPAIRED_EVENT = "geometrie_repariert"
COLLECTION_EVENT = "polygonanteile_aus_geometrycollection"


def _polygon_for_analysis(geometry, fid, code, events):
	"""Flächen aus FMZK-Zuschnitten vollständig und überprüfbar erhalten.

	Beim OGR-BBOX-Zuschnitt können gültige GeometryCollections mit
	Polygonen und flächenlosen Randlinien entstehen. Ausschließlich
	Polygonbestandteile tragen zur FMZK-Fläche bei. Positive
	Flächenverluste (z.B. überlappende Polygonbestandteile) stoppen.
	Original-GPKG und Feature-ID bleiben unverändert.
	"""
	original_type = geometry.geom_type
	reason = None
	if not geometry.is_valid:
		reason = explain_validity(geometry)
		geometry = make_valid(geometry)
		if not geometry.is_valid:
			raise ValueError(f"Feature {fid}: Geometrie nach make_valid "
				f"weiterhin ungültig ({reason})")

	if geometry.geom_type == "GeometryCollection":
		area_before = geometry.area
		if not math.isfinite(area_before):
			raise ValueError(f"Feature {fid}: GeometryCollection mit "
				"nicht-endlicher Fläche")
		polygon = polygonal_part(geometry)
		if area_before > 0 and (polygon is None or polygon.is_empty
			or not polygon.is_valid or polygon.area <= 0):
			raise ValueError(f"Feature {fid}: GeometryCollection enthält "
				"positive Fläche, aber keine gültige Polygongeometrie")
		if polygon is not None and not polygon.is_empty:
			area_after = polygon.area
			if not math.isfinite(area_after):
				raise ValueError(f"Feature {fid}: Polygonanteile mit "
					"nicht-endlicher Fläche")
			# Vorher: Summe der Polygonanteile in der Collection.
			# Nachher: deren Vereinigung ohne Linien und Punkte.
			# Überlappende Polygonanteile würden die Fläche verringern:
			# kein stilles Zusammenführen solcher Quellkonflikte.
			tolerance = max(1e-12, abs(area_before) * 1e-10)
			if abs(area_before - area_after) > tolerance:
				raise ValueError(f"Feature {fid}: GeometryCollection "
					"Flächenbilanz abweichend "
					f"({area_before:.12g} zu {area_after:.12g} m²); "
					"Polygonanteile nicht automatisch vereinigen")
			if not isinstance(polygon, (Polygon, MultiPolygon)):
				raise ValueError(f"Feature {fid}: nach Extraktion "
					f"unerwarteter Geometrietyp {polygon.geom_type}")
			if polygon.area > 0:
				events.append({
					"id": fid, "f_klasse": int(code),
					"status": COLLECTION_EVENT,
					"geometry_type": original_type,
					"bestandteile": [part.geom_type for part in geometry.geoms],
					"flaeche_original_m2": area_before,
					"flaeche_polygon_m2": area_after,
					"reason": "Polygonanteile aus GeometryCollection "
						"extrahiert; übrige Bestandteile ohne Flächenbeitrag",
				})
		geometry = polygon

	if geometry is None or geometry.is_empty or geometry.area <= 0:
		events.append({
			"id": fid, "f_klasse": int(code),
			"status": NO_AREA_EVENT,
			"geometry_type": original_type, "area_m2": 0,
			"reason": ("Nach make_valid ohne Polygonfläche: " + reason)
				if reason else "Keine Polygonfläche im zugeschnittenen Ausschnitt",
		})
		return None

	if not isinstance(geometry, (Polygon, MultiPolygon)):
		raise ValueError(f"Feature {fid}: Nicht-Polygon mit positiver "
			f"Fläche ({geometry.geom_type}); manuell prüfen")
	if not geometry.is_valid or not math.isfinite(geometry.area):
		raise ValueError(f"Feature {fid}: Polygongeometrie ungültig "
			"oder Fläche nicht endlich")

	if reason is not None:
		events.append({
			"id": fid, "f_klasse": int(code),
			"status": REPAIRED_EVENT,
			"geometry_type": original_type,
			"reason": reason,
		})
	return geometry


def load_polygons(source):
	source = Path(source)
	if not source.is_file():
		raise FileNotFoundError(f"Fehlendes lokales GeoPackage: {source}")
	manifest_path = source.with_suffix(".json")
	if not manifest_path.is_file():
		raise FileNotFoundError(f"Extraktionsbericht fehlt: {manifest_path}")
	manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
	if manifest.get("output_layer") != "fmzk" or manifest.get("output_srs") != "EPSG:31256":
		raise ValueError("Der Extraktionsbericht muss Layer fmzk in EPSG:31256 ausweisen")
	bbox = parse_bbox(",".join(str(v) for v in manifest["bbox_lon_lat"]))
	clip = projected_clip(bbox)
	info = gpkg_info(source, "fmzk")
	geom_column = '"' + info["geometry_column"].replace('"', '""') + '"'
	uri = "file:" + quote(str(source.resolve()), safe="/") + "?mode=ro"
	features = []
	events = []
	raw_count = 0
	with sqlite3.connect(uri, uri=True) as connection:
		rows = connection.execute(f'SELECT "id", {geom_column}, "F_KLASSE", "F_KLASSE_TEXT" FROM "fmzk"')
		for fid, blob, code, label in rows:
			raw_count += 1
			if code is None:
				raise ValueError(f"Feature {fid}: F_KLASSE fehlt")
			geometry = decode_gpkg_geometry(blob, fid)
			geometry = _polygon_for_analysis(geometry, fid, code, events)
			if geometry is None:
				continue
			outside_area = geometry.difference(clip).area
			if outside_area > 0.01:
				raise ValueError(f"Feature {fid}: {outside_area:.3f} m² außerhalb des Testausschnitts")
			features.append((fid, int(code), label or "", geometry))
	if raw_count != manifest.get("feature_count"):
		raise ValueError(f"Feature-Anzahl {raw_count} != Manifest {manifest.get('feature_count')}")
	if raw_count != len(features) + sum(
		item["status"] == NO_AREA_EVENT for item in events
	):
		raise ValueError("FMZK-Flächenbilanz: unbearbeitete Quell-Features")
	if not features:
		raise ValueError(f"FMZK-Ausschnitt {source} enthält keine Flächen")
	collections = [item["id"] for item in events
		if item["status"] == COLLECTION_EVENT]
	if collections:
		ids = ",".join(map(str, collections[:20]))
		if len(collections) > 20:
			ids += ",..."
		print(f"FMZK-Hinweis: {source}: {len(collections)} "
			f"GeometryCollections mit erhaltener Polygonfläche, IDs: {ids}; "
			"Details im Kataster-/Straßenraum-Bericht")
	excluded = [item["id"] for item in events if item["status"] == NO_AREA_EVENT]
	if excluded:
		identifiers = ",".join(map(str, excluded[:20]))
		if len(excluded) > 20:
			identifiers += ",..."
		print(f"FMZK-Hinweis: {source}: {len(excluded)} flächenlose "
			f"Zuschnittreste ohne Beitrag zur Fläche, IDs: {identifiers}; "
			"Quelldatei unverändert, Details im Kataster-/Straßenraum-Bericht")
	return features, manifest, clip, events
