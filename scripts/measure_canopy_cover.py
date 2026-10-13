#!/usr/bin/env python3
"""Methodenunabhängige Baumkronen-Überschirmung gegen eine Straßenraum-Maske.

Input: beliebige valide Baumkronen-Polygon-FeatureCollection in EPSG:4326,
sowie die stabile Straßenraum-Schnittstelle von Modul 2.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from pyproj import Transformer
from shapely import make_valid, union_all
from shapely.geometry import Polygon, MultiPolygon, mapping, shape
from shapely.ops import transform

from scripts.analyze_gpkg import polygonal_part
from scripts.fmzk_source import load_polygons
from scripts.measure_ground_greening import load_street_mask

DEFAULT_STREET = Path("data/processed/street_space/fmzk_strassenraum.geojson")
DEFAULT_FMZK = Path("data/processed/fmzk_test.gpkg")
DEFAULT_CROWNS = Path("data/processed/baumkronen/baumkronen_kreise.geojson")
DEFAULT_OUT = Path("data/processed/ueberschirmung")


def read_crown_polygons(path):
	path = Path(path)
	if not path.is_file():
		raise FileNotFoundError(f"Kronenpolygon-GeoJSON fehlt: {path}")
	data = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
		raise ValueError("Kronendaten müssen Polygon-GeoJSON FeatureCollection sein")
	if "crs" in data:
		raise ValueError("Kronen-GeoJSON mit abweichendem CRS nicht unterstützt; EPSG:4326 erforderlich")
	features = data.get("features")
	if not isinstance(features, list) or not features:
		raise ValueError("Kronen-GeoJSON enthält keine Features")
	transformer = Transformer.from_crs("EPSG:4326", "EPSG:31256", always_xy=True).transform
	parts = []
	repairs = 0
	for i, f in enumerate(features):
		if not isinstance(f, dict) or f.get("type") != "Feature" or not f.get("geometry"):
			raise ValueError(f"Kronenfeature {i}: ungültiges Feature")
		geom = shape(f["geometry"])
		if not isinstance(geom, (Polygon, MultiPolygon)):
			raise ValueError(f"Kronenfeature {i}: Polygon/MultiPolygon erwartet")
		if not geom.is_valid:
			geom = polygonal_part(make_valid(geom))
			repairs += 1
		if geom is None or geom.is_empty or geom.area <= 0 or not geom.is_valid:
			raise ValueError(f"Kronenfeature {i}: ungültige Polygongeometrie")
		geom = transform(transformer, geom)
		if not geom.is_valid:
			geom = polygonal_part(make_valid(geom))
			repairs += 1
		if geom is None or geom.is_empty or geom.area <= 0 or not geom.is_valid:
			raise ValueError(f"Kronenfeature {i}: ungültige transformierte Geometrie")
		parts.append(geom)
	return union_all(parts), {"quell_features": len(parts), "reparaturen": repairs,
		"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def measure_coverage(street, crowns):
	if street.is_empty or street.area <= 0 or not street.is_valid:
		raise ValueError("Straßenraum ist keine valide Flächenmaske")
	if crowns.is_empty or not crowns.is_valid:
		raise ValueError("Kronenmaske ist leer oder ungültig")
	covered = street.intersection(crowns)
	if covered.is_empty:
		area = 0.0
	else:
		area = covered.area
	return {
		"strassenraum_m2": street.area,
		"ueberschirmt_m2": area,
		"ueberschirmungsgrad_pct": 100 * area / street.area,
		"ausserhalb_strassenraum_m2": crowns.difference(street).area,
		"baumkronen_union_m2": crowns.area,
	}, covered


def run(street=DEFAULT_STREET, crowns=DEFAULT_CROWNS, fmzk=DEFAULT_FMZK,
	output=DEFAULT_OUT):
	_, manifest, clip, _ = load_polygons(fmzk)
	street_mask, street_meta = load_street_mask(street, clip)
	crown_mask, crown_meta = read_crown_polygons(crowns)
	metrics, covered = measure_coverage(street_mask, crown_mask)
	out = Path(output)
	out.mkdir(parents=True, exist_ok=True)
	to_lonlat = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform
	geometry = mapping(transform(to_lonlat, covered)) if covered and not covered.is_empty else None
	geojson = {"type": "FeatureCollection", "features": [{
		"type": "Feature",
		"properties": {"definition": "baumkronen_schnitt_strassenraum",
			"anteil_pct": metrics["ueberschirmungsgrad_pct"]},
		"geometry": geometry,
	}] if geometry is not None else []}
	(out / "ueberschirmte_flaeche.geojson").write_text(
		json.dumps(geojson, ensure_ascii=False) + "\n", encoding="utf-8")
	report = {
		"schema_version": 1,
		"datum_utc": datetime.now(timezone.utc).isoformat(),
		"status": "vorläufig, abhängig von Kronenquelle und Straßenraummaske",
		"gebiet_bbox_lon_lat": manifest["bbox_lon_lat"],
		"eingaben": {
			"strassenraum_geojson": str(street),
			"strassenraum": street_meta,
			"baumkronen_geojson": str(crowns),
			"baumkronen": crown_meta,
			"fmzk_geopackage": str(fmzk),
		},
		"kennzahlen": metrics,
		"hinweise": [
			"Alle Kronenflächen vor Messung geometrisch vereinigt; überlappende Kronen nicht doppelt gezählt.",
			"Kronen von Bäumen außerhalb des Straßenraums zählen, soweit ihre Polygonfläche die Straßenraum-Maske schneidet.",
			"Kreise aus Stammpunkten sind Näherungen; Luftbild-/Rasterkronen können später dieselbe Schnittstelle verwenden.",
			"Der Wert ist unabhängig vom Bodenbegrünungsanteil und darf nicht einfach addiert werden.",
		],
		"ausgabe_geojson": str(out / "ueberschirmte_flaeche.geojson"),
	}
	(out / "ueberschirmung_bericht.json").write_text(
		json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	print(f"Straßenraum: {metrics['strassenraum_m2']:.2f} m²")
	print(f"Kronenüberschirmung: {metrics['ueberschirmt_m2']:.2f} m²")
	print(f"Überschirmungsgrad: {metrics['ueberschirmungsgrad_pct']:.2f} %")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--street-geojson", type=Path, default=DEFAULT_STREET)
	parser.add_argument("--crowns-geojson", type=Path, default=DEFAULT_CROWNS)
	parser.add_argument("--fmzk", type=Path, default=DEFAULT_FMZK)
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
	args = parser.parse_args()
	try:
		run(street=args.street_geojson, crowns=args.crowns_geojson, fmzk=args.fmzk,
			output=args.out_dir)
	except (OSError, ValueError, TypeError, KeyError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
