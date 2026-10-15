"""Gemeinsamer, rein lesender FMZK-Adapter für unabhängige Analyse-Module.

Die Quelle ist das bereits extrahierte lokale GeoPackage (EPSG:31256).
Die Funktionen enthalten keine Logik zur Straßenraum-Klassifikation.
"""
import json
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


def _polygon_for_analysis(geometry, fid, code, events):
	"""Erhalte alle echten Flächen; dokumentiere flächenlose Zuschnittreste.

	ogr2ogr -clipsrc kann ein berührendes FMZK-Objekt als gültige
	LineString-/leere (Multi)Polygon-Geometrie exportieren. Ein
	0-m²-Rest darf keine Straßenraumfläche erzeugen. Er bleibt
	nachweisbar im unveränderten Quell-GPKG samt FID.
	"""
	original_type = geometry.geom_type
	if not geometry.is_valid:
		reason = explain_validity(geometry)
		repaired = make_valid(geometry)
		polygon = polygonal_part(repaired)
		if polygon is None or polygon.is_empty or polygon.area <= 0:
			if repaired.area > 0:
				raise ValueError(f"Feature {fid}: Geometrie enthält positive "
					f"Fläche, aber keine reparierbare Polygonfläche ({reason})")
			events.append({
				"id": fid, "f_klasse": int(code),
				"status": NO_AREA_EVENT,
				"geometry_type": original_type,
				"area_m2": 0,
				"reason": f"Nach make_valid ohne Polygonfläche: {reason}",
			})
			return None
		if not polygon.is_valid:
			raise ValueError(f"Feature {fid}: polygonale Geometrie "
				f"nicht reparierbar ({reason})")
		events.append({
			"id": fid, "f_klasse": int(code),
			"status": REPAIRED_EVENT,
			"geometry_type": original_type,
			"reason": reason,
		})
		geometry = polygon
	if not isinstance(geometry, (Polygon, MultiPolygon)):
		if not geometry.is_empty and geometry.area > 0:
			raise ValueError(f"Feature {fid}: Nicht-Polygon mit positiver "
				f"Fläche ({geometry.geom_type}); manuell prüfen")
		events.append({
			"id": fid, "f_klasse": int(code),
			"status": NO_AREA_EVENT, "geometry_type": original_type,
			"area_m2": 0,
			"reason": "Keine Polygongeometrie im zugeschnittenen Ausschnitt",
		})
		return None
	if geometry.is_empty or geometry.area <= 0:
		events.append({
			"id": fid, "f_klasse": int(code),
			"status": NO_AREA_EVENT, "geometry_type": original_type,
			"area_m2": 0,
			"reason": "Polygon ohne positive Fläche im Zuschnitt",
		})
		return None
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
	excluded = [item["id"] for item in events if item["status"] == NO_AREA_EVENT]
	if excluded:
		identifiers = ",".join(map(str, excluded[:20]))
		if len(excluded) > 20:
			identifiers += ",..."
		print(f"FMZK-Hinweis: {source}: {len(excluded)} flächenlose "
			f"Zuschnittreste ohne Beitrag zur Fläche, IDs: {identifiers}; "
			"Quelldatei unverändert, Details im Kataster-/Straßenraum-Bericht")
	return features, manifest, clip, events
