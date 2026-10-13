#!/usr/bin/env python3
"""Bodenbegrünung im Straßenraum aus einer austauschbaren Polygonmaske messen.

Die Straßenraum-GeoJSON-Datei liefert nur die räumliche Bezugsfläche.
Die Grünflächen stammen unabhängig davon aus dem lokalen FMZK-GeoPackage.
Weder Kataster noch das Straßenraum-Erzeugungsverfahren werden hier importiert.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from pyproj import Transformer
from shapely import make_valid, union_all
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.ops import transform

from scripts.analyze_gpkg import polygonal_part
from scripts.analyze_street_space import GREEN_CODES, load_polygons

DEFAULT_STREET = Path("data/processed/street_space/fmzk_strassenraum.geojson")
DEFAULT_FMZK = Path("data/processed/fmzk_test.gpkg")
DEFAULT_OUTPUT = Path("data/processed/bodenbegruenung")
SCHEMA_VERSION = 1


def polygonal_geometry(geometry, *, label):
	"""Nur Polygon/MultiPolygon akzeptieren; nichtpolygonale Reparaturreste abweisen."""
	if not isinstance(geometry, (Polygon, MultiPolygon)):
		raise ValueError(f"{label}: Polygon/MultiPolygon erwartet, erhalten {geometry.geom_type}")
	if geometry.is_empty or geometry.area <= 0:
		raise ValueError(f"{label}: leere oder flächenlose Geometrie")
	repaired = False
	if not geometry.is_valid:
		geometry = polygonal_part(make_valid(geometry))
		repaired = True
	if geometry is None or geometry.is_empty or not geometry.is_valid or geometry.area <= 0:
		raise ValueError(f"{label}: Polygon kann nicht repariert werden")
	return geometry, repaired


def load_street_mask(path, clip):
	"""Modulvertrag: Polygon-FeatureCollection in EPSG:4326, gleiche Test-BBOX."""
	path = Path(path)
	if not path.is_file():
		raise FileNotFoundError(f"Straßenraum-GeoJSON fehlt: {path}")
	document = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
		raise ValueError("Straßenraum-Eingabe muss eine GeoJSON-FeatureCollection sein")
	if "crs" in document:
		raise ValueError("GeoJSON muss EPSG:4326 verwenden und darf kein abweichendes crs-Attribut enthalten")
	features = document.get("features")
	if not isinstance(features, list) or not features:
		raise ValueError("Straßenraum-GeoJSON enthält keine Features")
	project = Transformer.from_crs("EPSG:4326", "EPSG:31256", always_xy=True).transform
	parts = []
	repairs = 0
	outside_m2 = 0.0
	for index, feature in enumerate(features):
		if not isinstance(feature, dict) or feature.get("type") != "Feature" or not feature.get("geometry"):
			raise ValueError(f"Straßenraum-Feature {index}: ungültiges Feature")
		geometry = shape(feature["geometry"])
		if any(not math.isfinite(value) for value in geometry.bounds):
			raise ValueError(f"Straßenraum-Feature {index}: ungültige Koordinaten")
		min_x, min_y, max_x, max_y = geometry.bounds
		if not (-180 <= min_x <= max_x <= 180 and -90 <= min_y <= max_y <= 90):
			raise ValueError(f"Straßenraum-Feature {index}: Geometrie muss EPSG:4326 sein")
		geometry, repaired = polygonal_geometry(geometry, label=f"Straßenraum-Feature {index}")
		repairs += int(repaired)
		geometry = transform(project, geometry)
		geometry, projected_repair = polygonal_geometry(geometry, label=f"Projiziertes Straßenraum-Feature {index}")
		repairs += int(projected_repair)
		outside = geometry.difference(clip).area
		outside_m2 += outside
		if outside > max(0.10, geometry.area * 0.000001):
			raise ValueError(f"Straßenraum-Feature {index}: {outside:.3f} m² außerhalb des FMZK-Testausschnitts")
		clipped = geometry.intersection(clip)
		if clipped.area > 0:
			parts.append(clipped)
	if not parts:
		raise ValueError("Straßenraum-Maske ist innerhalb des Testausschnitts leer")
	mask = union_all(parts)
	mask, repaired = polygonal_geometry(mask, label="Vereinigte Straßenraum-Maske")
	return mask, {
		"eingabe_features": len(features),
		"reparierte_geometrien": repairs + int(repaired),
		"ausserhalb_testausschnitt_m2": outside_m2,
		"masken_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
	}


def measure_ground_greening(mask, fmzk_features, *, green_codes=GREEN_CODES):
	"""Geometrische Vereinigungen verhindern Doppelzählungen im Zähler und Nenner.

	Einträge aus FMZK: (fid, klasse, klassenbezeichnung, geometrie in EPSG:31256).
	Die Fläche eines grünen Quellpolygons wird stets auf die Straßenmaske beschnitten.
	"""
	if not isinstance(mask, (Polygon, MultiPolygon)) or mask.is_empty or mask.area <= 0:
		raise ValueError("Straßenmaske benötigt gültige Polygonfläche")
	if not mask.is_valid:
		raise ValueError("Straßenmaske ist ungültig")
	green_parts = []
	by_code = defaultdict(list)
	review_parts = []
	source_count = 0
	green_count = 0
	seen_ids = set()
	all_source_geometries = []
	for fid, code, label, geom in fmzk_features:
		source_count += 1
		if fid in seen_ids:
			raise ValueError(f"Doppelte FMZK-FID: {fid}")
		seen_ids.add(fid)
		geom, _ = polygonal_geometry(geom, label=f"FMZK {fid}")
		all_source_geometries.append(geom)
		if code not in green_codes:
			continue
		green_count += 1
		if not geom.intersects(mask):
			continue
		part = geom.intersection(mask)
		if part.area <= 0:
			continue
		part = polygonal_part(part)
		if part is None or part.is_empty:
			continue
		green_parts.append(part)
		by_code[int(code)].append(part)
		review_parts.append((fid, int(code), label, geom.area, part))
	if not source_count:
		raise ValueError("Keine FMZK-Quellflächen vorhanden")
	green_union = union_all(green_parts) if green_parts else None
	numerator = green_union.area if green_union is not None else 0.0
	denominator = mask.area
	if numerator > denominator + 0.001:
		raise ValueError("Grünfläche übersteigt Straßenraumfläche: Geometriefehler")
	class_areas = {
		str(code): union_all(parts).area if parts else 0.0
		for code, parts in sorted(by_code.items())
	}
	for code in sorted(green_codes):
		class_areas.setdefault(str(code), 0.0)
	class_areas = dict(sorted(class_areas.items(), key=lambda item: int(item[0])))
	fmzk_union = union_all(all_source_geometries)
	not_mapped = mask.difference(fmzk_union).area
	report = {
		"strassenraum_flaeche_m2": denominator,
		"bodenbegruenung_flaeche_m2": numerator,
		"bodenbegruenungsanteil_pct": numerator / denominator * 100,
		"nicht_begruent_oder_anders_klassifiziert_m2": max(0.0, denominator - numerator),
		"strassenraum_ohne_fmzk_flaechendeckung_m2": not_mapped,
		"gruen_flaeche_pro_klasse_m2": class_areas,
		"gruen_klassen_ueberlagerung_m2": max(0.0, sum(class_areas.values()) - numerator),
		"fmzk_features": source_count,
		"fmzk_gruen_features": green_count,
		"gruen_features_mit_strassenueberschneidung": len(review_parts),
		"gruen_quellpolygon_ueberschneidung_m2": sum(part.area for *_, part in review_parts) - numerator,
	}
	return report, review_parts


def write_outputs(report, parts, street_path, fmzk_path, output_path, *, street_meta, manifest):
	out = Path(output_path)
	to_wgs84 = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform
	output_geojson = {"type": "FeatureCollection", "features": []}
	for fid, code, label, source_area, part in parts:
		# Zur Sichtung je FMZK-Objekt; Flächenstatistik verwendet die Vereinigungsfläche.
		output_geojson["features"].append({
			"type": "Feature",
			"properties": {
				"fid": fid, "f_klasse": code, "f_klasse_text": label,
				"gruenflaeche_im_strassenraum_m2": part.area,
				"quellpolygon_flaeche_m2": source_area,
				"anteil_des_quellpolygons_im_strassenraum_pct": part.area / source_area * 100,
			},
			"geometry": mapping(transform(to_wgs84, part)),
		})
	quality_notes = [
		"Straßenraumgrenze ist eine austauschbare vorläufige GIS-Arbeitsfläche, keine amtlich festgestellte Widmung.",
		"Bodenbegrünung basiert ausschließlich auf FMZK F_KLASSE 58/69, nicht auf Baumkronen.",
		"Zähler = Vereinigungsfläche der FMZK-Grünpolygone geschnitten mit der Straßenmaske.",
		"Nenner = Vereinigungsfläche der Straßenraum-Polygone; kein Summieren überlappender Einzelobjekte.",
		"Ungeklärte Straßenraumflächen außerhalb der gewählten Maske werden nicht mitgerechnet.",
	]
	if report["strassenraum_ohne_fmzk_flaechendeckung_m2"] > 0.05:
		quality_notes.append("Achtung: Ein Teil des Straßenraums hat keine FMZK-Flächendeckung.")
	if report["gruen_klassen_ueberlagerung_m2"] > 0.05:
		quality_notes.append("Grünklassen überlappen räumlich; bei Klassensummen keine Doppelzählungen übersehen.")
	full_report = {
		"schema_version": SCHEMA_VERSION,
		"stand_utc": datetime.now(timezone.utc).isoformat(),
		"gebiet_bbox_lon_lat": manifest["bbox_lon_lat"],
		"definition": {
			"gruenklassen_fmzk": sorted(GREEN_CODES),
			"kennzahl": "bodenbegruenungsanteil_pct",
			"einheit": "Prozent der vorläufigen Straßenraumfläche",
			"quelle": "FMZK-Grünflächen geschnitten mit austauschbarer Straßenraum-Maske",
		},
		"eingaben": {
			"strassenraum_geojson": str(street_path),
			"fmzk_geopackage": str(fmzk_path),
			"strassenraum_format": "GeoJSON FeatureCollection Polygon/MultiPolygon EPSG:4326",
			"fmzk_format": "GeoPackage Layer fmzk EPSG:31256",
			"strassenraum": street_meta,
		},
		"kennzahlen": report,
		"hinweise": quality_notes,
		"ausgaben": {
			"bericht": str(out / "bodenbegruenung_bericht.json"),
			"geometrien": str(out / "bodenbegruenung_flaechen.geojson"),
		},
	}
	out.mkdir(parents=True, exist_ok=True)
	(out / "bodenbegruenung_flaechen.geojson").write_text(
		json.dumps(output_geojson, ensure_ascii=False) + "\n", encoding="utf-8"
	)
	(out / "bodenbegruenung_bericht.json").write_text(
		json.dumps(full_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
	)
	return full_report


def run(street=DEFAULT_STREET, fmzk=DEFAULT_FMZK, output=DEFAULT_OUTPUT):
	fmzk_features, manifest, clip, _ = load_polygons(fmzk)
	mask, street_meta = load_street_mask(street, clip)
	report, parts = measure_ground_greening(mask, fmzk_features)
	final = write_outputs(report, parts, street, fmzk, output, street_meta=street_meta, manifest=manifest)
	metrics = final["kennzahlen"]
	print(f"Straßenraum: {metrics['strassenraum_flaeche_m2']:.2f} m²")
	print(f"Bodenbegrünung: {metrics['bodenbegruenung_flaeche_m2']:.2f} m²")
	print(f"Bodenbegrünungsanteil: {metrics['bodenbegruenungsanteil_pct']:.2f} %")
	print(f"FMZK-Grünpolygone mit Straßenraumüberschneidung: {len(parts)}")
	print(f"Ausgabe: {Path(output).resolve()}")
	return final


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--street-geojson", type=Path, default=DEFAULT_STREET,
		help="Beliebige Polygon-FeatureCollection in EPSG:4326 für denselben FMZK-Testausschnitt")
	parser.add_argument("--fmzk", type=Path, default=DEFAULT_FMZK, help="Lokaler FMZK-Testausschnitt")
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
	args = parser.parse_args()
	try:
		run(args.street_geojson, args.fmzk, args.out_dir)
	except (OSError, ValueError, KeyError, TypeError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
