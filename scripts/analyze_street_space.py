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
from urllib.parse import quote

from pyproj import Transformer
from shapely import make_valid, union_all
from shapely.geometry import mapping, Polygon, MultiPolygon
from shapely.ops import transform
from shapely.validation import explain_validity

from scripts.analyze_gpkg import decode_gpkg_geometry, polygonal_part
from scripts.extract_fmzk import gpkg_info, parse_bbox, projected_clip

DEFAULT_SOURCE = Path("data/processed/fmzk_test.gpkg")
DEFAULT_OUTPUT = Path("data/processed/street_space")

# Sicher erkennbarer Kern öffentlicher Verkehrsflächen – bewusst NICHT
# als vollständige Grenze des öffentlichen Straßenraums ausgeben.
CORE_CODES = frozenset((21, 23, 24, 33))
GREEN_CODES = frozenset((58, 69))
AMBIGUOUS_CODES = frozenset((39, 59))
PRIVATE_CONTEXT_CODES = frozenset((25, 26, 51))
REVIEW_CODES = CORE_CODES | GREEN_CODES | AMBIGUOUS_CODES | PRIVATE_CONTEXT_CODES
CANDIDATE_CODES = GREEN_CODES | AMBIGUOUS_CODES
CANDIDATE_FIELDS = (
	"id", "f_klasse", "f_klasse_text", "rolle", "status",
	"flaeche_m2", "abstand_kern_m", "randkontakt_m",
	"randkontakt_anteil_pct", "flaeche_im_2m_umfeld_pct",
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
		"flaeche_m2": round(geometry.area, 2),
		"abstand_kern_m": round(distance, 3),
		"randkontakt_m": round(contact_m, 2),
		"randkontakt_anteil_pct": round(100 * contact_m / geometry.length, 2) if geometry.length else 0,
		"flaeche_im_2m_umfeld_pct": round(near_share, 2),
	}


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


def build_review(features, *, tolerance_m=0.25, near_m=2.0, min_contact_m=0.5):
	if not (0 < tolerance_m <= 2 and 0 < near_m <= 20 and 0 < min_contact_m <= 10):
		raise ValueError("Unzulässige Prüfdistanzen")
	core_shapes = [geom for _, code, _, geom in features if code in CORE_CODES]
	if not core_shapes:
		raise ValueError("Keine Kernflächen (21/23/24/33) im Testausschnitt")
	core = union_all(core_shapes)
	if core.is_empty or core.area <= 0:
		raise ValueError("Vereinigte Kernfläche leer")
	boundary_band = core.boundary.buffer(tolerance_m)
	near_band = core.buffer(near_m)

	review = []
	candidates = []
	by_class_and_status = defaultdict(list)
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
			"flaeche_m2": round(geometry.area, 2),
		}
		if code in CANDIDATE_CODES:
			properties.update(classify_contact(
				geometry, core, boundary_band, near_band,
				near_m=near_m, min_contact_m=min_contact_m,
			))
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
	}


def write_review(review, output_dir, source, manifest, clip, repairs, *, tolerance_m, near_m, min_contact_m):
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
			"status_ueberlappt_mindestflaeche_m2": 0.05,
		},
		"original_klassen_anzahl": review["class_counts"],
		"geometrie_reparaturen": repairs,
		"kandidaten_je_klasse_und_lage": review["summary"],
	}
	(output_dir / "strassenraum_bericht.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	return report


def analyze(source=DEFAULT_SOURCE, output_dir=DEFAULT_OUTPUT, *, tolerance_m=0.25, near_m=2.0, min_contact_m=0.5):
	features, manifest, clip, repairs = load_polygons(source)
	review = build_review(features, tolerance_m=tolerance_m, near_m=near_m, min_contact_m=min_contact_m)
	report = write_review(review, output_dir, source, manifest, clip, repairs,
		tolerance_m=tolerance_m, near_m=near_m, min_contact_m=min_contact_m)
	print(f"FMZK-Features: {report['features_gesamt']}, Kernfläche: {report['kern_union_m2']:.2f} m²")
	print(f"Prüfkandidaten: {len(review['candidates'])} (58/69 Grün; 39/59 unklare Nutzungen)")
	for row in review["summary"]:
		print(f"  Klasse {row['f_klasse']:2d} {row['status']:22s} {row['objekte']:4d} Objekte  {row['flaeche_union_m2']:10.2f} m²")
	if repairs:
		print(f"Geometriereparaturen: {len(repairs)} (siehe Bericht)")
	print(f"Lokale Dateien unter: {Path(output_dir).resolve()}")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
	parser.add_argument("--randtoleranz-m", type=float, default=0.25)
	parser.add_argument("--nahe-m", type=float, default=2.0)
	parser.add_argument("--mindest-randkontakt-m", type=float, default=0.5)
	args = parser.parse_args()
	try:
		analyze(args.source, args.out_dir, tolerance_m=args.randtoleranz_m,
			near_m=args.nahe_m, min_contact_m=args.mindest_randkontakt_m)
	except (ValueError, KeyError, FileNotFoundError, OSError, sqlite3.Error) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
