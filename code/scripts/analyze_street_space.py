#!/usr/bin/env python3
"""FMZK-Straßenraum: gesicherte Verkehrsflächen und benachbarte Prüfkandidaten.

Noch KEINE vollständige Straßenraumgrenze und KEIN Grünanteil von Straßen.
Alle Flächen bleiben lokal; die Original-FMZK wird nur lesend geöffnet.
"""

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import sqlite3

from pyproj import Transformer
from shapely import union_all
from shapely.geometry import mapping
from shapely.ops import transform

from scripts.street_embedding import CORE_CLASSES, make_contact_surfaces, measure_embedding
from scripts.fmzk_source import (
	FMZK_GROUND_GREEN_CODES, NO_AREA_EVENT, REPAIRED_EVENT, COLLECTION_EVENT,
	load_polygons,
)

DEFAULT_SOURCE = Path("data/processed/fmzk_test.gpkg")
DEFAULT_OUTPUT = Path("data/processed/street_space")

# Vorläufiger FMZK-Verkehrsflächenkern einschließlich Klasse 25 (Gehweg/Radweg) – NICHT
# als vollständige Grenze des öffentlichen Straßenraums ausgeben.
CORE_CODES = frozenset(CORE_CLASSES)
GREEN_CODES = FMZK_GROUND_GREEN_CODES
AMBIGUOUS_CODES = frozenset((59,))
PRIVATE_CONTEXT_CODES = frozenset((26, 51))
REVIEW_CODES = CORE_CODES | GREEN_CODES | AMBIGUOUS_CODES | PRIVATE_CONTEXT_CODES
CANDIDATE_CODES = GREEN_CODES | AMBIGUOUS_CODES
CANDIDATE_FIELDS = (
	"id", "f_klasse", "f_klasse_text", "rolle", "status",
	"flaeche_m2", "abstand_kern_m", "randkontakt_m",
	"randkontakt_anteil_pct", "flaeche_im_umfeld_pct",
	"einbettung", "mehrseitiger_kontakt", "gegenueber_verschiedene_klassen",
	"kontaktklassen", "kontakt_sektoren", "kontakt_rand_pct",
	"richtung_ungeklaert_m", "kontakt_21_m", "kontakt_23_m",
	"kontakt_24_m", "kontakt_25_m", "kontakt_33_m", "kontakt_39_m",
)


def classify_contact(geometry, core, boundary_band, near_band, *, near_m, min_contact_m):
	"""Nur topologische Lage, KEINE automatische Widmung als öffentliche Fläche."""
	overlap_m2 = geometry.intersection(core).area
	contact_m = geometry.boundary.intersection(boundary_band).length
	distance = geometry.distance(core)
	near_share = geometry.intersection(near_band).area / geometry.area * 100
	if overlap_m2 > 0.05:
		status = "ueberlappt_kern"
	elif contact_m >= min_contact_m:
		status = "grenzt_an_kern"
	elif distance <= near_m:
		status = "nahe_kern"
	else:
		status = "fern_vom_kern"
	return {
		"status": status,
		"flaeche_m2": geometry.area,
		"abstand_kern_m": round(distance, 3),
		"randkontakt_m": round(contact_m, 2),
		"randkontakt_anteil_pct": round(100 * contact_m / geometry.length, 2) if geometry.length else 0,
		"flaeche_im_umfeld_pct": round(near_share, 2),
	}


def build_review(features, *, tolerance_m=0.25, near_m=2.0, min_contact_m=0.5,
	min_sector_m=0.8, probe_m=0.03):
	if not (0 < tolerance_m <= 2 and 0 < near_m <= 20 and 0 < min_contact_m <= 10
		and 0 < min_sector_m <= 10 and 0 < probe_m <= 1):
		raise ValueError("Unzulässige Prüfdistanzen")
	core_shapes = [geom for _, code, _, geom in features if code in CORE_CODES]
	if not core_shapes:
		raise ValueError(f"Keine Kernflächen {sorted(CORE_CODES)} im Testausschnitt")
	core = union_all(core_shapes)
	if core.is_empty or core.area <= 0:
		raise ValueError("Vereinigte Kernfläche leer")
	boundary_band = core.boundary.buffer(tolerance_m)
	near_band = core.buffer(near_m)
	contact_surfaces = make_contact_surfaces(features)
	contact_buffers = {code: geom.buffer(tolerance_m) for code, geom in contact_surfaces.items()}
	prepared_core_buffer = core.buffer(tolerance_m)

	review = []
	candidates = []
	by_class_and_status = defaultdict(list)
	embedding_counts = Counter()
	raw_counts = Counter()
	for fid, code, label, geometry in features:
		raw_counts[code] += 1
		if code not in REVIEW_CODES:
			continue
		if code in CORE_CODES:
			role = "kern"
		elif code in GREEN_CODES:
			role = "gruen_pruefen"
		elif code in AMBIGUOUS_CODES:
			role = "unklar_pruefen"
		else:
			role = "privat_kontext"
		properties = {
			"id": fid,
			"f_klasse": code,
			"f_klasse_text": label,
			"rolle": role,
			"status": "kern" if role == "kern" else "nur_kontext",
			"flaeche_m2": geometry.area,
		}
		if code in CANDIDATE_CODES:
			properties.update(classify_contact(
				geometry, core, boundary_band, near_band,
				near_m=near_m, min_contact_m=min_contact_m,
			))
			properties.update(measure_embedding(
				geometry, contact_surfaces,
				tolerance_m=tolerance_m, minimum_sector_m=min_sector_m,
				probe_m=probe_m,
				has_core_overlap=properties["status"] == "ueberlappt_kern",
				prepared_class_buffers=contact_buffers,
				prepared_core_buffer=prepared_core_buffer,
			))
			embedding_counts[(code, properties["einbettung"])] += 1
			by_class_and_status[(code, properties["status"])].append(geometry)
			candidates.append({field: properties.get(field) for field in CANDIDATE_FIELDS})
		review.append((properties, geometry))

	rows = []
	for (code, status), geometries in sorted(by_class_and_status.items()):
		rows.append({
			"f_klasse": code,
			"status": status,
			"objekte": len(geometries),
			"flaeche_union_m2": round(union_all(geometries).area, 2),
		})
	return {
		"core": core,
		"features": review,
		"candidates": candidates,
		"summary": rows,
		"class_counts": dict(sorted(raw_counts.items())),
		"embedding_counts": [
			{"f_klasse": code, "einbettung": kind, "objekte": amount}
			for (code, kind), amount in sorted(embedding_counts.items())
		],
	}


def write_review(review, output_dir, source, manifest, clip, repairs, *, tolerance_m, near_m, min_contact_m,
	min_sector_m, probe_m):
	output_dir = Path(output_dir)
	output_dir.mkdir(parents=True, exist_ok=True)
	to_wgs84 = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform

	def geojson_feature(props, geom):
		return {
			"type": "Feature",
			"properties": props,
			"geometry": mapping(transform(to_wgs84, geom)),
		}

	review_path = output_dir / "strassenraum_pruefung.geojson"
	review_path.write_text(json.dumps({
		"type": "FeatureCollection",
		"features": [geojson_feature(props, geom) for props, geom in review["features"]],
	}, ensure_ascii=False), encoding="utf-8")
	core_path = output_dir / "strassenraum_kern.geojson"
	core_path.write_text(json.dumps({
		"type": "FeatureCollection",
		"features": [geojson_feature({"rolle": "kern_vereinigt", "flaeche_m2": round(review["core"].area, 2)}, review["core"])],
	}, ensure_ascii=False), encoding="utf-8")
	csv_path = output_dir / "strassenraum_kandidaten.csv"
	with csv_path.open("w", encoding="utf-8-sig", newline="") as output:
		writer = csv.DictWriter(output, fieldnames=CANDIDATE_FIELDS)
		writer.writeheader()
		writer.writerows(review["candidates"])
	report = {
		"hinweis": "Explorative Lageprüfung, keine öffentliche Straßenraumgrenze, keine Grünprozente je Straße.",
		"quelle": str(source),
		"crs_berechnung": "EPSG:31256",
		"crs_geojson": "EPSG:4326",
		"bbox_lon_lat": manifest["bbox_lon_lat"],
		"bbox_m2": round(clip.area, 2),
		"features_gesamt": sum(review["class_counts"].values()),
		"kern_klassen": sorted(CORE_CODES),
		"kern_union_m2": round(review["core"].area, 2),
		"kandidaten_klassen": sorted(CANDIDATE_CODES),
		"kandidaten_flächen_sind_keine_bestätigten_strassenflächen": True,
		"private_kontext_klassen": sorted(PRIVATE_CONTEXT_CODES),
		"parameter": {
			"randtoleranz_m": tolerance_m,
			"nahe_distanz_m": near_m,
			"mindest_randkontakt_m": min_contact_m,
			"mindest_sektorkontakt_m": min_sector_m,
			"normalen_pruefabstand_m": probe_m,
			"status_ueberlappt_mindestflaeche_m2": 0.05,
		},
		"original_klassen_anzahl": review["class_counts"],
		"geometrie_reparaturen": [e for e in repairs if e["status"] == REPAIRED_EVENT],
		"flaechenlose_zuschnittreste": [e for e in repairs if e["status"] == NO_AREA_EVENT],
		"polygonanteile_aus_collections": [e for e in repairs if e["status"] == COLLECTION_EVENT],
		"fmzk_quell_features": manifest["feature_count"],
		"kandidaten_je_klasse_und_lage": review["summary"],
		"kandidaten_je_klasse_und_einbettung": review["embedding_counts"],
	}
	(output_dir / "strassenraum_bericht.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	return report


def analyze(source=DEFAULT_SOURCE, output_dir=DEFAULT_OUTPUT, *, tolerance_m=0.25, near_m=2.0,
	min_contact_m=0.5, min_sector_m=0.8, probe_m=0.03):
	features, manifest, clip, repairs = load_polygons(source)
	review = build_review(features, tolerance_m=tolerance_m, near_m=near_m,
		min_contact_m=min_contact_m, min_sector_m=min_sector_m, probe_m=probe_m)
	report = write_review(review, output_dir, source, manifest, clip, repairs,
		tolerance_m=tolerance_m, near_m=near_m, min_contact_m=min_contact_m,
		min_sector_m=min_sector_m, probe_m=probe_m)
	print(f"FMZK-Features: {report['features_gesamt']}, Kernfläche: {report['kern_union_m2']:.2f} m²")
	print(f"Prüfkandidaten: {len(review['candidates'])} (58/69 Grün; 59 unklare Nutzung)")
	for row in review["summary"]:
		print(f"  Klasse {row['f_klasse']:2d} {row['status']:22s} {row['objekte']:4d} Objekte  {row['flaeche_union_m2']:10.2f} m²")
	print("Einbettung (nur topologische Hinweise, keine öffentliche Widmung):")
	for row in review["embedding_counts"]:
		print(f"  Klasse {row['f_klasse']:2d} {row['einbettung']:34s} {row['objekte']:4d} Objekte")
	if report["geometrie_reparaturen"]:
		print(f"Geometriereparaturen: {len(report['geometrie_reparaturen'])} (siehe Bericht)")
	if report["polygonanteile_aus_collections"]:
		print(f"GeometryCollections mit erhaltener Polygonfläche: {len(report['polygonanteile_aus_collections'])} (siehe Bericht)")
	if report["flaechenlose_zuschnittreste"]:
		print(f"Flächenlose Zuschnittreste: {len(report['flaechenlose_zuschnittreste'])} (siehe Bericht)")
	print(f"Lokale Dateien unter: {Path(output_dir).resolve()}")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
	parser.add_argument("--randtoleranz-m", type=float, default=0.25)
	parser.add_argument("--nahe-m", type=float, default=2.0)
	parser.add_argument("--mindest-randkontakt-m", type=float, default=0.5)
	parser.add_argument("--mindest-sektorkontakt-m", type=float, default=0.8)
	parser.add_argument("--normalen-probe-m", type=float, default=0.03)
	args = parser.parse_args()
	try:
		analyze(args.source, args.out_dir, tolerance_m=args.randtoleranz_m,
			near_m=args.nahe_m, min_contact_m=args.mindest_randkontakt_m,
			min_sector_m=args.mindest_sektorkontakt_m, probe_m=args.normalen_probe_m)
	except (ValueError, KeyError, FileNotFoundError, OSError, sqlite3.Error) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
