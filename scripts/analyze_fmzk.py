#!/usr/bin/env python3
"""Lokale FMZK-Probe: BBOX-beschnittene Polygonflächen je Nutzungsklasse."""

import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import box, mapping, shape
from shapely.ops import transform, unary_union

# Quelle: https://www.wien.gv.at/pdf/ma41/fmzk-attribute-wertebereiche.pdf
FMZK_CLASSES = {
	11: "Gebäude", 12: "Überbauung / Verbindungsgang", 13: "Flugdach",
	14: "Glashaus", 16: "Brückenpfeiler", 19: "Sonstige Gebäudefläche",
	21: "Fahrbahn (inkl. Radweg)", 22: "Verkehrsinsel",
	23: "Gehsteig / Geh- und Radweg im öffentlichen Gut", 24: "Fußgängerzone",
	25: "Fuß- und Radverkehr auf Privatgrund", 26: "Kfz-Verkehrsfläche auf Privatgrund",
	27: "Schienenbereich", 28: "Selbstständiger Gleiskörper", 29: "Bahnhofsbereich",
	30: "Zebrastreifen", 31: "Straßenmöbel", 32: "Fahrbahnaufwölbung / Rampe",
	33: "Ruhender Verkehr im öffentlichen Gut", 39: "Sonstige Verkehrsfläche",
	41: "Natürliches Gewässer", 42: "Schwimmbecken / privates Biotop",
	43: "Brunnen / künstliche Wasserfläche", 44: "Gerinne", 49: "Sonstige Gewässerfläche",
	51: "Hof / Innenhof", 52: "Wald / Baumbestand", 53: "Naturnahe Wiese",
	54: "Feld / Acker / Beet", 55: "Weingarten", 57: "Gräberfeld",
	58: "Rasen / sonstige unversiegelte Fläche", 59: "Sonstige befestigte / versiegelte Fläche",
	60: "Baustelle", 61: "Sportfeld", 62: "Deponie", 63: "Lagerplatz",
	64: "Schottergrube", 69: "Sonstige Grünfläche", 71: "Mauer",
	73: "Sockelzaun", 74: "Stiege / Stufe / Rampe", 81: "Denkmal",
	82: "Telefonzelle", 83: "ÖV-Stationseinrichtung", 84: "Kiosk",
	86: "Portal", 91: "Rohrleitung", 92: "Energieversorgung",
	93: "Klärbecken", 99: "Sonstige nicht zuordenbare Fläche",
}


def parse_class(raw, layer, feature_id):
	if raw is None:
		raise ValueError(f"{layer}: Feature {feature_id} ohne F_KLASSE")
	try:
		code = int(raw)
	except (TypeError, ValueError) as exc:
		raise ValueError(f"{layer}: Feature {feature_id} mit ungültiger F_KLASSE={raw!r}") from exc
	if str(raw) not in (str(code), f"{code}.0"):
		raise ValueError(f"{layer}: Feature {feature_id} mit nichtganzzahliger F_KLASSE={raw!r}")
	if code not in FMZK_CLASSES:
		raise ValueError(f"{layer}: Feature {feature_id} mit unbekannter F_KLASSE={code}; Klassentabelle prüfen")
	return code


def analyze(raw_dir, output_dir):
	manifest = json.loads((raw_dir / "manifest.json").read_text(encoding="utf-8"))
	if manifest.get("crs") != "EPSG:4326":
		raise ValueError("Nur WFS-GeoJSON in EPSG:4326 wird unterstützt")
	bbox_values = manifest.get("bbox_lon_lat")
	if not isinstance(bbox_values, list) or len(bbox_values) != 4:
		raise ValueError("Fehlende bbox_lon_lat im Manifest")
	west, south, east, north = map(float, bbox_values)
	if not (west < east and south < north):
		raise ValueError("Ungültige BBOX im Manifest")
	bbox = box(west, south, east, north)
	project = Transformer.from_crs("EPSG:4326", "EPSG:31256", always_xy=True).transform
	bbox_area = transform(project, bbox).area
	clipped_features = []
	class_groups = defaultdict(list)
	counts = defaultdict(int)
	clipped_counts = defaultdict(int)
	layer_counts = {}

	for layer_name in ("verkehr1", "verkehr2"):
		path = raw_dir / f"fmzk_{layer_name}.geojson"
		collection = json.loads(path.read_text(encoding="utf-8"))
		if collection.get("type") != "FeatureCollection" or not isinstance(collection.get("features"), list):
			raise ValueError(f"{path} enthält keine FeatureCollection")
		features = collection["features"]
		expected = manifest.get("layers", {}).get(layer_name, {}).get("feature_count")
		if len(features) != expected:
			raise ValueError(f"{path}: {len(features)} Features, laut Manifest {expected}")
		layer_counts[layer_name] = len(features)
		for index, feature in enumerate(features):
			feature_id = feature.get("id", index)
			properties = feature.get("properties") or {}
			code = parse_class(properties.get("F_KLASSE"), layer_name, feature_id)
			key = (layer_name, code)
			counts[key] += 1
			geom_dict = feature.get("geometry")
			if geom_dict is None:
				raise ValueError(f"{layer_name}: Feature {feature_id} ohne Geometrie")
			geom = shape(geom_dict)
			if geom.geom_type not in ("Polygon", "MultiPolygon"):
				raise ValueError(f"{layer_name}: Feature {feature_id} ist {geom.geom_type}, nicht Polygon")
			if not geom.is_valid:
				raise ValueError(f"{layer_name}: Feature {feature_id} besitzt ungültige Geometrie (nicht automatisch repariert)")
			cut = geom.intersection(bbox)
			if cut.is_empty or cut.area <= 0:
				continue
			cut_projected = transform(project, cut)
			if cut_projected.area <= 0:
				continue
			clipped_counts[key] += 1
			class_groups[key].append(cut_projected)
			clipped_features.append({
				"type": "Feature",
				"id": f"{layer_name}:{feature_id}",
				"properties": {
					**properties,
					"QUELLE": layer_name,
					"FMZK_TEXT": FMZK_CLASSES[code],
					"AREA_M2": round(cut_projected.area, 2),
				},
				"geometry": mapping(cut),
			})

	rows = []
	all_shapes = []
	for key in sorted(counts):
		layer_name, code = key
		shapes = class_groups.get(key, [])
		union_area = unary_union(shapes).area if shapes else 0.0
		rows.append({
			"layer": layer_name,
			"f_klasse": code,
			"bedeutung": FMZK_CLASSES[code],
			"features_geliefert": counts[key],
			"features_im_ausschnitt": clipped_counts[key],
			"fläche_m2": round(union_area, 2),
			"anteil_bbox_prozent": round(100 * union_area / bbox_area, 3),
		})
		all_shapes.extend(shapes)

	union_area = unary_union(all_shapes).area if all_shapes else 0.0
	class_area_sum = sum(r["fläche_m2"] for r in rows)
	report = {
		"note": "Nur Flächenstatistik der geladenen WFS-Layer, kein Anteil am öffentlichen Straßenraum und kein Gartenstraßen-Score.",
		"data_retrieved_at_utc": manifest.get("retrieved_at_utc"),
		"bbox_lon_lat": bbox_values,
		"area_crs": "EPSG:31256",
		"bbox_area_m2": round(bbox_area, 2),
		"union_area_m2": round(union_area, 2),
		"overlap_across_classes_m2": round(max(0.0, class_area_sum - union_area), 2),
		"layer_feature_counts": layer_counts,
		"categories": rows,
	}
	output_dir.mkdir(parents=True, exist_ok=True)
	with (output_dir / "fmzk_klassen.csv").open("w", newline="", encoding="utf-8-sig") as file:
		writer = csv.DictWriter(file, fieldnames=list(rows[0]) if rows else ["layer", "f_klasse", "bedeutung", "features_geliefert", "features_im_ausschnitt", "fläche_m2", "anteil_bbox_prozent"])
		writer.writeheader()
		writer.writerows(rows)
	(output_dir / "fmzk_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
	(output_dir / "fmzk_ausschnitt.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": clipped_features}, ensure_ascii=False), encoding="utf-8")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
	parser.add_argument("--out-dir", type=Path, default=Path("data/processed"))
	args = parser.parse_args()
	try:
		report = analyze(args.raw_dir, args.out_dir)
	except (ValueError, FileNotFoundError, KeyError, OSError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")
	print(f"BBOX: {report['bbox_area_m2']:.1f} m²; FMZK-Polygonvereinigung: {report['union_area_m2']:.1f} m²")
	if report["overlap_across_classes_m2"] > 1:
		print(f"Achtung: {report['overlap_across_classes_m2']:.1f} m² Überlagerungen zwischen Klassen/Layern")
	for row in report["categories"]:
		print(f"{row['layer']:8s} {row['f_klasse']:2d} {row['features_im_ausschnitt']:4d} Objekte {row['fläche_m2']:11.1f} m²  {row['bedeutung']}")
	print(f"Ergebnis: {args.out_dir.resolve()}")


if __name__ == "__main__":
	main()
