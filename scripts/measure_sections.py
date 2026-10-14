#!/usr/bin/env python3
"""Modul 6 – integrierte abschnittsweise Grün-/Kronenauswertung, V0.

Verwendet ausdrücklich die bereits aufgeteilte, unveränderte GIP-V0-
Straßenraummaske (7-m-Kreis-Knotenbereiche). Bewertet die Abschnitte
UND die separat ungeklärten Flächen, damit Gebietssummen erhalten bleiben.

Geometrie und Fläche in EPSG:31256, GeoJSON-Ausgabe in EPSG:4326.
Keine Netzabfragen, neuen Kreuzungsgrenzen oder Gartenstraßen-Scores.
"""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from pyproj import Transformer
from shapely import union_all
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.ops import transform

from scripts.fmzk_source import FMZK_GROUND_GREEN_CODES, load_polygons
from scripts.measure_ground_greening import load_street_mask
from scripts.measure_canopy_cover import read_crown_polygons

DEFAULT_STREET = Path("data/processed/street_space/fmzk_strassenraum.geojson")
DEFAULT_FMZK = Path("data/processed/fmzk_test.gpkg")
DEFAULT_SECTIONS = Path("data/processed/strassenabschnitte/aufteilung_v0")
DEFAULT_A = Path("data/processed/baumkronen/baumkronen_kreise.geojson")
DEFAULT_B = Path("data/processed/baumkronen/variante_b/baumkronen_kombiniert.geojson")
DEFAULT_C = Path("data/processed/baumkronen/grm2023/processed/baumkronen_grm2023.geojson")
DEFAULT_OUTPUT = Path("data/processed/strassenabschnitte/kennzahlen_v0")
TO_METRIC = Transformer.from_crs("EPSG:4326", "EPSG:31256",
	always_xy=True).transform
TO_LONLAT = Transformer.from_crs("EPSG:31256", "EPSG:4326",
	always_xy=True).transform

CSV_FIELDS = (
	"gruppe", "id", "gip_objectid", "name", "status",
	"strassenraum_m2", "bodenbegruenung_m2", "bodenbegruenung_pct",
	"kronen_a_m2", "kronen_a_pct",
	"kronen_b_m2", "kronen_b_pct",
	"kronen_c_m2", "kronen_c_pct",
	"vegetation_d_m2", "vegetation_d_pct",
)
METRICS = (
	("bodenbegruenung", "bodenbegruenung"),
	("kronen_a", "kronen_a"),
	("kronen_b", "kronen_b"),
	("kronen_c", "kronen_c"),
	("vegetation_d", "vegetation_d"),
)


def sha256(path):
	"""Auch größere lokale GeoPackages ohne vollständiges Einlesen hashen."""
	digest = hashlib.sha256()
	with Path(path).open("rb") as handle:
		for chunk in iter(lambda: handle.read(1024 * 1024), b""):
			digest.update(chunk)
	return digest.hexdigest()


def tolerance(area):
	"""GeoJSON-Rückprojektion kann Grenzen um Millimeter verschieben.

	Die echte V0-Flächenbilanz stammt aus der metrischen Ursprungs-
	geometrie. Für den NEUEN Exportimport gelten max. 0,5 m²
	oder 0,001 % der Gesamtfläche; jede Abweichung wird ausgewiesen.
	"""
	return max(0.5, area * 1e-5)


def _close(label, actual, expected, limit):
	if not math.isfinite(actual) or abs(actual - expected) > limit:
		raise ValueError(f"{label}: {actual:.6f} m² statt "
			f"{expected:.6f} m²; Differenz "
			f"{actual-expected:.6f} m² (Toleranz {limit:.4f} m²)")


def _geometry(feature, *, label):
	if not isinstance(feature, dict) or feature.get("type") != "Feature":
		raise ValueError(f"{label}: GeoJSON-Feature fehlt")
	if not isinstance(feature.get("properties"), dict) or not feature.get("geometry"):
		raise ValueError(f"{label}: Geometrie/Properties fehlen")
	try:
		geo = shape(feature["geometry"])
	except (TypeError, ValueError, KeyError) as exc:
		raise ValueError(f"{label}: ungültige Geometrie") from exc
	if not isinstance(geo, (Polygon, MultiPolygon)) or (
		geo.is_empty or not geo.is_valid or geo.area <= 0
	):
		raise ValueError(f"{label}: gültige Polygonfläche erwartet")
	if any(not math.isfinite(v) for v in geo.bounds):
		raise ValueError(f"{label}: nicht-endliche Koordinaten")
	minx, miny, maxx, maxy = geo.bounds
	if not (-180 <= minx <= maxx <= 180 and -90 <= miny <= maxy <= 90):
		raise ValueError(f"{label}: Koordinaten nicht EPSG:4326")
	projected = transform(TO_METRIC, geo)
	if projected.is_empty or not projected.is_valid or projected.area <= 0:
		raise ValueError(f"{label}: projizierte Polygonfläche ungültig")
	return projected


def read_features(path, *, label):
	path = Path(path)
	data = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
		raise ValueError(f"{label}: GeoJSON FeatureCollection erforderlich")
	if "crs" in data:
		raise ValueError(f"{label}: explizites crs in EPSG:4326 GeoJSON unzulässig")
	features = data.get("features")
	if not isinstance(features, list) or not features:
		raise ValueError(f"{label}: keine Polygon-Features")
	return features


def read_partition(directory, street, *, street_sha256):
	"""V0-Bilanz, Input-Hash und geometrische Partition strikt gegenprüfen."""
	directory = Path(directory)
	report = json.loads((directory / "abschnitte_bericht.json").read_text(
		encoding="utf-8"))
	if report.get("schema_version") != 1 or "EXPERIMENTELL" not in report.get("status", ""):
		raise ValueError("Abschnittsbericht: keine bekannte V0-Partition")
	params = report.get("parameter") or {}
	if not (params.get("knotenradius_m") == 7
		and params.get("sample_spacing_m") == 5
		and params.get("max_axis_distance_m") == 25
		and params.get("gip_standard_fow") == 3):
		raise ValueError("Abschnittsbericht: V0-Parameter (7/5/25/FOW=3) verändert")
	if (report.get("quelle") or {}).get("strassenraum_sha256") != street_sha256:
		raise ValueError("V0 wurde auf einer anderen Straßenraummaske berechnet (SHA-256)")
	limit = tolerance(street.area)
	area_info = report.get("bilanz") or {}
	_close("V0 Straßenraumfläche", area_info.get("strassenraum_m2", float("nan")),
		street.area, limit)
	parts = []
	numerical_slivers = []
	ids = set()
	for group, filename in (
		("abschnitt", "abschnitte_flaechen.geojson"),
		("ungeklaert", "abschnitte_ungeklaert.geojson"),
	):
		for index, feature in enumerate(read_features(directory / filename, label=group)):
			properties = feature["properties"]
			fid = feature.get("id")
			if not isinstance(fid, str) or not fid.strip() or fid in ids:
				raise ValueError(f"{group} {index}: fehlende/doppelte Feature-ID")
			ids.add(fid)
			if group == "abschnitt":
				gip_id = str(properties.get("gip_objectid") or "")
				if not gip_id or fid != f"gip:{gip_id}":
					raise ValueError(f"{fid}: GIP-ID passt nicht zu Feature-ID")
				if properties.get("status") != "experimentell_achsennaehe":
					raise ValueError(f"{fid}: kein unveränderter V0-Abschnitt")
			else:
				gip_id = None
				if (not fid.startswith("ungeklaert:")
					or properties.get("status") not in (
						"knotenbereich", "sonderachse", "nicht_zugeordnet"
					)):
					raise ValueError(f"{fid}: keine V0-Restflächenklasse")
			original_area = float(properties.get("flaeche_m2", float("nan")))
			# V0 kann nahezu flächenlose Restfetzen (etwa 2e-9 m²)
			# explizit exportieren. Die Rundreise durch WGS84
			# kollabiert manche davon: unter 1e-4 m² als separat
			# dokumentiertes numerisches Reststück behandeln.
			if (group == "ungeklaert"
				and properties.get("status") == "nicht_zugeordnet"
				and math.isfinite(original_area) and 0 <= original_area < 1e-4):
				numerical_slivers.append({"id": fid, "quelle_m2": original_area})
				continue
			geom = _geometry(feature, label=fid)
			_close(f"{fid} Quellenfläche", geom.area,
				original_area, limit)
			parts.append({
				"gruppe": group, "id": fid, "gip_objectid": gip_id,
				"name": properties.get("name") or "",
				"status": properties["status"],
				"geometry": geom,
			})
	section_count = sum(p["gruppe"] == "abschnitt" for p in parts)
	if section_count != area_info.get("anzahl_zugeordnete_abschnitte"):
		raise ValueError("Zahl V0-Abschnitte stimmt nicht mit Partitionbericht überein")
	assigned = sum(p["geometry"].area for p in parts
		if p["gruppe"] == "abschnitt")
	unresolved = sum(p["geometry"].area for p in parts
		if p["gruppe"] == "ungeklaert")
	_close("V0 zugeordnete Fläche", assigned,
		area_info.get("zugeordnet_m2", float("nan")), limit)
	_close("V0 ungeklärte Fläche", unresolved,
		area_info.get("ungeklaert_m2", float("nan")), limit)
	combined = union_all([p["geometry"] for p in parts])
	overlap = max(0., assigned + unresolved - combined.area)
	missing = street.difference(combined).area
	outside = combined.difference(street).area
	for label, amount in (
		("Überlappung V0", overlap), ("fehlende Straßenfläche", missing),
		("außerhalb Straßenraum", outside),
	):
		if amount > limit:
			raise ValueError(f"{label}: {amount:.6f} m² (Limit {limit:.4f})")
	_close("Summe aller Flächen", assigned + unresolved, street.area, limit)
	return parts, {
		"abschnitte": section_count,
		"ungeklaerte_klassen": sum(p["gruppe"] == "ungeklaert" for p in parts),
		"strassenraum_m2": street.area,
		"zugeordnet_m2": assigned,
		"ungeklaert_m2": unresolved,
		"geometrische_ueberlappung_m2": overlap,
		"fehlende_flaeche_m2": missing,
		"ausserhalb_strassenraum_m2": outside,
		"toleranz_m2": limit,
		"numerische_reststuecke_unter_1e_4_m2": numerical_slivers,
	}, report


def compute_rows(parts, street, masks):
	"""Nur geometrische Schnitte, keine abgeleiteten Fantasie-/Summenquoten."""
	limit = tolerance(street.area)
	rows = []
	for part in parts:
		geometry = part["geometry"]
		row = {key: part[key] for key in (
			"gruppe", "id", "gip_objectid", "name", "status"
		)}
		row["strassenraum_m2"] = geometry.area
		for metric, mask_name in METRICS:
			mask = masks.get(mask_name)
			area_key = metric + "_m2"
			pct_key = metric + "_pct"
			if mask is None:
				row[area_key] = None
				row[pct_key] = None
			else:
				value = geometry.intersection(mask).area
				if value > geometry.area + limit:
					raise ValueError(f"{part['id']}: {metric} größer als Abschnitt")
				row[area_key] = value
				row[pct_key] = 100 * value / geometry.area
		rows.append(row)
	metrics_totals = {}
	for metric, mask_name in METRICS:
		mask = masks.get(mask_name)
		if mask is None:
			metrics_totals[metric] = None
			continue
		by_group = {
			group: sum(row[metric + "_m2"] for row in rows
				if row["gruppe"] == group)
			for group in ("abschnitt", "ungeklaert")
		}
		expected = street.intersection(mask).area
		_close(f"Bilanz {metric}", sum(by_group.values()), expected, limit)
		if expected > street.area + limit:
			raise ValueError(f"{metric}: Ergebnis über Straßenraumfläche")
		metrics_totals[metric] = {
			"gesamt_m2": expected,
			"gesamt_pct": expected / street.area * 100,
			"abschnitte_m2": by_group["abschnitt"],
			"ungeklaert_m2": by_group["ungeklaert"],
			"bilanzdifferenz_m2": sum(by_group.values()) - expected,
		}
	return rows, metrics_totals


def _geojson(rows, parts, group):
	features = []
	for row, part in zip(rows, parts):
		if row["gruppe"] != group:
			continue
		features.append({
			"type": "Feature", "id": row["id"],
			"properties": {k: v for k, v in row.items() if k != "id"}
				| {"id": row["id"]},
			"geometry": mapping(transform(TO_LONLAT, part["geometry"])),
		})
	return {"type": "FeatureCollection", "features": features}


def run(*, sections=DEFAULT_SECTIONS, street=DEFAULT_STREET,
	fmzk=DEFAULT_FMZK, canopy_a=DEFAULT_A, canopy_b=DEFAULT_B,
	canopy_c=DEFAULT_C, vegetation_d=None, output=DEFAULT_OUTPUT):
	"""Ein integrierter Offline-Durchlauf; erst validieren, dann schreiben."""
	output = Path(output)
	files = {
		"geojson": output / "abschnitte_kennzahlen.geojson",
		"ungeklaert_geojson": output / "ungeklaerte_kennzahlen.geojson",
		"csv": output / "abschnitte_kennzahlen.csv",
		"bericht": output / "abschnitte_kennzahlen_bericht.json",
	}
	if any(path.exists() for path in files.values()):
		raise FileExistsError("Modul-6-Ausgabe existiert bereits; "
			"ein neues --out-dir wählen")
	fmzk_features, manifest, clip, _ = load_polygons(fmzk)
	street_geom, street_meta = load_street_mask(street, clip)
	parts, partition_stats, partition_report = read_partition(
		sections, street_geom, street_sha256=street_meta["masken_sha256"])
	green_parts = [geom.intersection(street_geom)
		for _fid, code, _text, geom in fmzk_features
		if code in FMZK_GROUND_GREEN_CODES and geom.intersects(street_geom)]
	green = union_all(green_parts) if green_parts else Polygon()
	masks = {"bodenbegruenung": green}
	sources = {
		"strassenraum": {"pfad": str(street), "sha256": street_meta["masken_sha256"]},
		"fmzk": {"pfad": str(fmzk), "sha256": sha256(fmzk),
			"gruenklassen": sorted(FMZK_GROUND_GREEN_CODES)},
		"v0_abschnitte": {
			"pfad": str(Path(sections) / "abschnitte_flaechen.geojson"),
			"sha256": sha256(Path(sections) / "abschnitte_flaechen.geojson")},
		"v0_ungeklaert": {
			"pfad": str(Path(sections) / "abschnitte_ungeklaert.geojson"),
			"sha256": sha256(Path(sections) / "abschnitte_ungeklaert.geojson")},
		"v0_bericht": {
			"pfad": str(Path(sections) / "abschnitte_bericht.json"),
			"sha256": sha256(Path(sections) / "abschnitte_bericht.json")},
	}
	for key, path in (
		("kronen_a", canopy_a), ("kronen_b", canopy_b),
		("kronen_c", canopy_c), ("vegetation_d", vegetation_d),
	):
		if path is None:
			masks[key] = None
			continue
		mask, metadata = read_crown_polygons(path)
		masks[key] = mask
		sources[key] = {"pfad": str(path), **metadata}
	rows, totals = compute_rows(parts, street_geom, masks)
	report = {
		"schema_version": 1,
		"erstellt_utc": datetime.now(timezone.utc).isoformat(),
		"status": "ERSTER TESTLAUF – V0-ABSCHNITTE FACHLICH VORLAEUFIG",
		"bbox_lon_lat": manifest["bbox_lon_lat"],
		"v0_parameter": partition_report["parameter"],
		"quellen": sources, "partition_pruefung": partition_stats,
		"gesamtkennzahlen": totals,
		"abschnitte": [row for row in rows if row["gruppe"] == "abschnitt"],
		"ungeklaerte_flaechen": [row for row in rows if row["gruppe"] == "ungeklaert"],
		"hinweise": [
			"Abschnittsflächen stammen aus V0: 7-m-Kreis-Kreuzungen, fachlich noch nicht final geprüft.",
			"Kreuzungs- und Restflächen zählen vollständig zur Gebietsbilanz, nicht zur Abschnittsquote.",
			"Baumkronen A/B/C sind alternative Modelle und werden nicht addiert.",
			"Bodenbegrünung ist separat von Baumkronen zu verstehen; Überlagerungen sind möglich.",
			"Vegetation D ist optional und KEINE bestätigte Baumkronenüberschirmung.",
			"Prozentanteile immer aus einzelnen geometrischen Flächen berechnet, nie gemittelt.",
			"Keine Gartenstraßen-Bewertung und keine neuen Schwellenwerte.",
		],
		"ausgaben": {key: str(value) for key, value in files.items()},
	}
	# Keine Dateien vor bestandener Vollflächen- und Kennzahlenbilanz.
	output.mkdir(parents=True, exist_ok=True)
	for kind, group in (("geojson", "abschnitt"), ("ungeklaert_geojson", "ungeklaert")):
		files[kind].write_text(json.dumps(_geojson(rows, parts, group),
			ensure_ascii=False) + "\n", encoding="utf-8")
	with files["csv"].open("w", newline="", encoding="utf-8-sig") as handle:
		writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, delimiter=";")
		writer.writeheader()
		writer.writerows(rows)
	files["bericht"].write_text(json.dumps(report, ensure_ascii=False,
		indent=2) + "\n", encoding="utf-8")
	print(f"Modul 6: {partition_stats['abschnitte']} Abschnitte; "
		f"{partition_stats['ungeklaerte_klassen']} ungeklärte Flächenklassen")
	for key, data in totals.items():
		if data is not None:
			print(f"  {key}: {data['gesamt_m2']:.2f} m² / "
				f"{data['gesamt_pct']:.2f} % (inklusive ungeklärter Flächen)")
	print(f"Bericht: {files['bericht']}")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--sections-dir", type=Path, default=DEFAULT_SECTIONS)
	parser.add_argument("--street-geojson", type=Path, default=DEFAULT_STREET)
	parser.add_argument("--fmzk", type=Path, default=DEFAULT_FMZK)
	parser.add_argument("--canopy-a", type=Path, default=DEFAULT_A)
	parser.add_argument("--canopy-b", type=Path, default=DEFAULT_B)
	parser.add_argument("--canopy-c", type=Path, default=DEFAULT_C)
	parser.add_argument("--vegetation-geojson", type=Path,
		help="Optional: separat validierte D2=0,20-Vegetations-Polygonmaske; "
		"nicht als Kronenfläche ausgeben")
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
	args = parser.parse_args()
	try:
		run(sections=args.sections_dir, street=args.street_geojson,
			fmzk=args.fmzk, canopy_a=args.canopy_a, canopy_b=args.canopy_b,
			canopy_c=args.canopy_c, vegetation_d=args.vegetation_geojson,
			output=args.out_dir)
	except (OSError, ValueError, TypeError, KeyError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
