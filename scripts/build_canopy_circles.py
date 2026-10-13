#!/usr/bin/env python3
"""Methode A – ausschließlich Wiener Baumkataster: Kronenkreise aus Klassenmittelwerten.

Diese Ein-Quellen-Variante bleibt unverändert mit dem dokumentierten
Referenzwert 7,82 % vergleichbar. OSM und Baumreihen gehören zu Methode B.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

from scripts.fmzk_source import load_polygons
from scripts.canopy_tree_common import (
	CITY_DIAMETER_FIELD,
	DUPLICATE_DISTANCE_M,
	read_points,
	parse_wien_crown_range,
	diameter_from_properties,
	parse_trees,
	merge_trees,  # alter Export für rückwärtskompatible Tests, nicht im A-Lauf
	crowns_from_trees,
)

DEFAULT_FMZK = Path("data/processed/fmzk_test.gpkg")
DEFAULT_OUTPUT = Path("data/processed/baumkronen")


def run(*, wien, osm=None, fmzk=DEFAULT_FMZK, output=DEFAULT_OUTPUT,
	osm_default_diameter=None, duplicate_distance=DUPLICATE_DISTANCE_M):
	if osm is not None or osm_default_diameter is not None or duplicate_distance != DUPLICATE_DISTANCE_M:
		raise ValueError("Methode A verarbeitet nur Wiener Baumkataster. Für OSM bitte build_canopy_combined (Methode B) verwenden.")
	if wien is None:
		raise ValueError("Methode A benötigt --wien mit der WFS-GeoJSON-Datei")
	_, manifest, area, _ = load_polygons(fmzk)
	points, digest = read_points(wien, provider="wien")
	parsed, excluded = parse_trees(points, "wien")
	features, spatial_exclusions = crowns_from_trees(parsed, area_of_interest=area)
	if not features:
		raise ValueError("Keine Baumkronen überschneiden das Testgebiet; Quelle/BBOX prüfen")
	output = Path(output)
	output.mkdir(parents=True, exist_ok=True)
	geojson_path = output / "baumkronen_kreise.geojson"
	geojson_path.write_text(json.dumps({
		"type": "FeatureCollection", "features": features,
	}, ensure_ascii=False) + "\n", encoding="utf-8")
	sources = {"wien": {
		"path": str(wien), "sha256": digest,
		"eingabe_features": len(points), "verwertbare_baeume": len(parsed),
		"kronenklassen_txt_haeufigkeiten": dict(sorted(
			Counter(str((item.get("properties") or {}).get(CITY_DIAMETER_FIELD))
				for item in points if isinstance(item, dict)
				and isinstance(item.get("properties"), dict)).items()
		)),
	}}
	report = {
		"schema_version": 1,
		"methode": "A – nur Wien: Mittelpunkt des Kronendurchmesser-Klassenintervalls; Kronenkreis um Stammpunkt",
		"status": "Vergleichsvariante A, keine vermessenen Kronenpolygone",
		"datum_utc": datetime.now(timezone.utc).isoformat(),
		"fmzk_bbox_lon_lat": manifest["bbox_lon_lat"],
		"quellen": sources,
		"ausgeschlossene_eingabefeatures": {"wien": excluded},
		"baumkronen": len(features),
		"quellen_im_ergebnis": {"wien": len(features)},
		"ausgeschlossen_raeumlich": spatial_exclusions,
		"osm_default_diameter_m": None,
		"osm_wien_dublettenabstand_m": DUPLICATE_DISTANCE_M,
		"moegliche_dubletten": [],
		"bemerkung": "Methode A enthält keine OSM-Daten. Kronendurchmesser nach KRONENDURCHMESSER_TXT als Mittelpunkt geschlossener Meterklassen, offene/unklare Klassen ausgeschlossen.",
		"ausgabe": str(geojson_path),
	}
	(output / "baumkronen_kreise_bericht.json").write_text(
		json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	print(f"Erzeugte Baumkronen-Kreise: {len(features)} (Methode A: ausschließlich Wien)")
	print(f"GeoJSON: {geojson_path}")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--wien", type=Path, required=True,
		help="Wiener Baumkataster WFS-GeoJSON")
	parser.add_argument("--fmzk", type=Path, default=DEFAULT_FMZK)
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
	args = parser.parse_args()
	try:
		run(wien=args.wien, fmzk=args.fmzk, output=args.out_dir)
	except (OSError, ValueError, KeyError, TypeError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
