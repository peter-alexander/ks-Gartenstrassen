#!/usr/bin/env python3
"""Methode B – Wiener Baumkataster + OSM-Einzelbäume und Baumreihen.

Eigenständiger Anbieter auf Basis der Kartensammlung-Baumdaten-Build-Logik:
Vorrang Wien > OSM-Einzelbaum > aus Baumreihen abgeleitete Positionen.
Die Wiener Teilmenge verwendet exakt denselben Klassenmittelwert-/Kreis-
Algorithmus wie A; OSM-Schätzungen sind im Output ausdrücklich markiert.
Die Berechnung des Überschirmungsgrads bleibt ein separates Modul.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from scripts.fmzk_source import load_polygons
from scripts.canopy_tree_common import read_points, parse_trees, crowns_from_trees
from scripts.canopy_osm_merge import selected_osm_trees

DEFAULT_FMZK = Path("data/processed/fmzk_test.gpkg")
DEFAULT_WIEN = Path("data/processed/baumkronen/baumkataster_wfs.geojson")
DEFAULT_OSM = Path("data/processed/baumkronen/osm/osm_baeume_overpass.json")
DEFAULT_OUT = Path("data/processed/baumkronen/variante_b")


def run(*, wien=DEFAULT_WIEN, osm=DEFAULT_OSM, fmzk=DEFAULT_FMZK,
	output=DEFAULT_OUT, allow_osm_estimates=True):
	_, manifest, area, _ = load_polygons(fmzk)
	city_features, city_sha = read_points(wien, provider="wien")
	city_trees, city_excluded = parse_trees(city_features, "wien")
	osm_path = Path(osm)
	if not osm_path.is_file():
		raise FileNotFoundError(f"OSM-Overpass-JSON fehlt: {osm_path}; zuerst fetch_osm_trees ausführen")
	osm_raw = osm_path.read_bytes()
	osm_doc = json.loads(osm_raw.decode("utf-8-sig"))
	osm_trees, merge_report = selected_osm_trees(city_features, osm_doc,
		allow_estimates=allow_osm_estimates)
	trees = city_trees + osm_trees
	polygons, spatial_exclusions = crowns_from_trees(trees, area_of_interest=area)
	if not polygons:
		raise ValueError("Methode B: Keine verwendbaren Kronenpolygone im FMZK-Testgebiet")
	# Die Zusatzeigenschaften sind nur bei OSM wichtig. Der aus Wien
	# stammende Teil bleibt geometrisch identisch zur Variante A.
	osm_by_id = {t["id"]: t for t in osm_trees}
	for feature in polygons:
		props = feature["properties"]
		identifier = props["source_id"]
		if props["source"] == "wien":
			props["KS_SOURCE"] = "wien_baumkataster"
			continue
		tree = osm_by_id[identifier]
		props["KS_SOURCE"] = tree["provider"]
		props["KS_ID"] = identifier
		props["OSM_ID"] = tree["osm_id"]
		props["OSM_TYPE"] = tree["osm_type"]
		props["OSM_TREE_ROW_INDEX"] = tree["osm_row_index"]
		props["OSM_TREE_COUNT"] = tree["osm_row_count"]
		props["osm_hoehe_annahme_m"] = tree["osm_height_m"]
		props["kronendurchmesser_geschaetzt"] = tree["diameter_quality"] != "osm_expliziter_kronendurchmesser"
	output = Path(output)
	output.mkdir(parents=True, exist_ok=True)
	geojson = output / "baumkronen_kombiniert.geojson"
	geojson.write_text(json.dumps({
		"type": "FeatureCollection", "features": polygons,
	}, ensure_ascii=False) + "\n", encoding="utf-8")
	source_counts = Counter(f["properties"]["source"] for f in polygons)
	status_counts = Counter(f["properties"]["diameter_status"] for f in polygons)
	report = {
		"schema_version": 1,
		"methode": "B – Wien + OSM: Baumdaten-Merge nach kartensammlung-overlay-builds/baumkataster",
		"zeit_utc": datetime.now(timezone.utc).isoformat(),
		"fmzk_bbox_lon_lat": manifest["bbox_lon_lat"],
		"referenz": "https://github.com/peter-alexander/kartensammlung-overlay-builds/blob/main/baumkataster/build.mjs",
		"bemerkung": "Original-Wien-Vorrang, OSM-Punkte, Baumreihensampling und Dublettenabstände. Distanzen metrisch EPSG:31256 statt vereinfachter WGS84-Skalierung. Fehlende OSM-Kronenwerte nach explizit dokumentierter Solar-3D-Formel geschätzt oder mit --strict-osm ausgeschlossen.",
		"quellen": {
			"wien": {
				"path": str(wien), "sha256": city_sha,
				"eingabe_punkte": len(city_features),
				"kronenklasse_verwertbar": len(city_trees),
				"ausgeschlossen_kronenklasse": city_excluded,
			},
			"osm": {
				"path": str(osm_path),
				"sha256": hashlib.sha256(osm_raw).hexdigest(),
				"elemente": len(osm_doc["elements"]),
				"quelle": "OpenStreetMap (Overpass), ODbL",
			},
		},
		"merge": {
			"prioritaet": ["wien_baumkataster", "osm_tree", "osm_tree_row"],
			"wien_osm_abstand_m": 4.0,
			"osm_nodes_abstand_m": 0.75,
			"baumreihe_gegen_explizite_baeume_m": 4.0,
			"baumreihe_gegen_baumreihe_m": 3.0,
			"baumreihe_abstand_standard_m": 8.0,
			"max_baumreihen_samples": 500,
			"osm_solar_ersatzdurchmesser_aktiv": bool(allow_osm_estimates),
			"osm_fallback": "Bei fehlendem Kronenmaß: Höhe aus OSM oder 12m; Durchmesser max(2,min(12, Höhe*0,5)), höchstens Höhe*1,2. Geschätzte Kronen sind keine Messwerte.",
			"statistik": merge_report,
		},
		"baumkronen_features": len(polygons),
		"quellen_im_ergebnis": dict(sorted(source_counts.items())),
		"qualitaetsstatus_im_ergebnis": dict(sorted(status_counts.items())),
		"ausgeschlossen_raeumlich": spatial_exclusions,
		"geojson": str(geojson),
	}
	report_path = output / "baumkronen_kombiniert_bericht.json"
	report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
		encoding="utf-8")
	print("Methode B – Baumkataster + OSM:")
	for key, count in sorted(source_counts.items()):
		print(f"  {key}: {count}")
	print(f"  Kronen gesamt: {len(polygons)}")
	print(f"  Geschätzte OSM-Kronen: {sum(n for key, n in status_counts.items() if key.startswith('solar_'))}")
	print(f"GeoJSON: {geojson}")
	print(f"Bericht: {report_path}")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--wien", type=Path, default=DEFAULT_WIEN)
	parser.add_argument("--osm", type=Path, default=DEFAULT_OSM,
		help="Rohes Overpass JSON aus fetch_osm_trees.py, nicht das zusammengeführte TileJSON")
	parser.add_argument("--fmzk", type=Path, default=DEFAULT_FMZK)
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
	parser.add_argument("--strict-osm", action="store_true",
		help="OSM-Bäume ohne expliziten Kronendurchmesser ausschließen (Vergleichsvariante)")
	args = parser.parse_args()
	try:
		run(wien=args.wien, osm=args.osm, fmzk=args.fmzk, output=args.out_dir,
			allow_osm_estimates=not args.strict_osm)
	except (OSError, ValueError, TypeError, KeyError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
