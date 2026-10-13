#!/usr/bin/env python3
"""Vergleicht alternative Kronenpolygon-GeoJSONs an derselben Straßenraum-Maske."""

import argparse
from datetime import datetime, timezone
from itertools import combinations
import json
from pathlib import Path

from shapely import union_all

from scripts.fmzk_source import load_polygons
from scripts.measure_ground_greening import load_street_mask
from scripts.measure_canopy_cover import read_crown_polygons, measure_coverage

DEFAULT_FMZK = Path("data/processed/fmzk_test.gpkg")
DEFAULT_STREET = Path("data/processed/street_space/fmzk_strassenraum.geojson")
DEFAULT_OUT = Path("data/processed/ueberschirmung/vergleich")


def compare_methods(street, candidate_geometries):
	if len(candidate_geometries) < 2:
		raise ValueError("Für den Vergleich mindestens zwei Kronenmethoden übergeben")
	metrics = {}
	clips = {}
	for name, geom in candidate_geometries.items():
		metrics[name], clips[name] = measure_coverage(street, geom)
	pairs = []
	for left, right in combinations(sorted(clips), 2):
		a, b = clips[left], clips[right]
		intersection = a.intersection(b).area
		union = a.union(b).area
		pairs.append({
			"methode_a": left, "methode_b": right,
			"uebereinstimmende_kronenflaeche_m2": intersection,
			"nur_a_m2": a.difference(b).area,
			"nur_b_m2": b.difference(a).area,
			"vereinigung_m2": union,
			"flaechen_iou": intersection / union if union > 0 else None,
		})
	return metrics, pairs


def parse_candidate(text):
	if "=" not in text:
		raise ValueError("Kandidatenformat: --candidate name=pfad.geojson")
	name, filepath = text.split("=", 1)
	if not name or not name.replace("_", "").replace("-", "").isalnum():
		raise ValueError(f"Ungültiger Methodenname: {name}")
	if not filepath:
		raise ValueError("GeoJSON-Pfad fehlt")
	return name, Path(filepath)


def run(*, candidates, fmzk=DEFAULT_FMZK, street=DEFAULT_STREET, output=DEFAULT_OUT):
	_, manifest, clip, _ = load_polygons(fmzk)
	street_mask, street_meta = load_street_mask(street, clip)
	methods = {}
	sources = {}
	for name, path in candidates:
		if name in methods:
			raise ValueError(f"Doppelte Methode: {name}")
		geom, meta = read_crown_polygons(path)
		methods[name] = geom
		sources[name] = {"geojson": str(path), **meta}
	metrics, pairs = compare_methods(street_mask, methods)
	report = {
		"schema_version": 1,
		"stand_utc": datetime.now(timezone.utc).isoformat(),
		"hinweis": "IoU/Übereinstimmung beschreibt den Unterschied der Verfahren, nicht ihre Genauigkeit gegenüber einer unabhängigen Referenz.",
		"testgebiet_bbox_lon_lat": manifest["bbox_lon_lat"],
		"strassenraum": {"geojson": str(street), **street_meta},
		"methoden": {name: {"quelle": sources[name], "kennzahlen": metrics[name]}
			for name in sorted(methods)},
		"paarweiser_vergleich": pairs,
	}
	output = Path(output)
	output.mkdir(parents=True, exist_ok=True)
	path = output / "kronenmethoden_vergleich.json"
	path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	for name in sorted(metrics):
		print(f"{name}: {metrics[name]['ueberschirmungsgrad_pct']:.2f} %")
	for pair in pairs:
		print(f"{pair['methode_a']} / {pair['methode_b']}: IoU={pair['flaechen_iou']}")
	print(f"Ausgabe: {path}")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--candidate", action="append", required=True,
		help="Zwei oder mehr Wiederholungen: --candidate wien=baumkronen_wien.geojson")
	parser.add_argument("--fmzk", type=Path, default=DEFAULT_FMZK)
	parser.add_argument("--street-geojson", type=Path, default=DEFAULT_STREET)
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
	args = parser.parse_args()
	try:
		candidates = [parse_candidate(text) for text in args.candidate]
		run(candidates=candidates, fmzk=args.fmzk,
			street=args.street_geojson, output=args.out_dir)
	except (OSError, ValueError, KeyError, TypeError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
