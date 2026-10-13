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
	repairs = []
	with sqlite3.connect(uri, uri=True) as connection:
		rows = connection.execute(f'SELECT "id", {geom_column}, "F_KLASSE", "F_KLASSE_TEXT" FROM "fmzk"')
		for fid, blob, code, label in rows:
			if code is None:
				raise ValueError(f"Feature {fid}: F_KLASSE fehlt")
			geometry = decode_gpkg_geometry(blob, fid)
			if not geometry.is_valid:
				reason = explain_validity(geometry)
				geometry = polygonal_part(make_valid(geometry))
				if geometry is None or geometry.is_empty or not geometry.is_valid:
					raise ValueError(f"Feature {fid}: polygonale Geometrie nicht reparierbar ({reason})")
				repairs.append({"id": fid, "f_klasse": code, "reason": reason})
			if not isinstance(geometry, (Polygon, MultiPolygon)) or geometry.is_empty or geometry.area <= 0:
				raise ValueError(f"Feature {fid}: flächenlose oder nicht-polygonale Geometrie")
			outside_area = geometry.difference(clip).area
			if outside_area > 0.01:
				raise ValueError(f"Feature {fid}: {outside_area:.3f} m² außerhalb des Testausschnitts")
			features.append((fid, int(code), label or "", geometry))
	if len(features) != manifest.get("feature_count"):
		raise ValueError(f"Feature-Anzahl {len(features)} != Manifest {manifest.get('feature_count')}")
	return features, manifest, clip, repairs
