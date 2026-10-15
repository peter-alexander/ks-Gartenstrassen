#!/usr/bin/env python3
"""Alle Polygone des lokalen FMZK-Ausschnitts in zwei GeoJSONs aufteilen.

Straßenraum: FMZK-Kern 21/23/24/25/33/39 oder Nicht-Kernfläche mit
mindestens 95 % räumlicher Deckung durch BEV-nfl 95/65 im Testausschnitt.
Keine rechtliche Aussage über die Öffentlichkeit des Straßenraums.
"""

import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from urllib.parse import quote

from pyproj import Transformer
from shapely import make_valid, union_all
from shapely.geometry import mapping, shape
from shapely.ops import transform

from scripts.analyze_gpkg import polygonal_part
from scripts.analyze_street_space import CORE_CODES, load_polygons

DEFAULT_SOURCE = Path("data/processed/fmzk_test.gpkg")
DEFAULT_KATASTER = Path("data/processed/kataster")
DEFAULT_OUTPUT = Path("data/processed/street_space")
STREET_USAGE_CODES = frozenset((65, 95))
DEFAULT_MIN_SHARE = 0.95
# Änderungen der Kernklassen ändern die Straßenraumfläche und invalidieren
# sämtliche davon abgeleiteten Straßenraum-/GIP-/Begrünungs-Caches.
STREET_CLASSIFICATION_VERSION = "fmzk-core-21-23-24-25-33-39-nfl-95-65-v2"


def read_json(path, *, expect_collection=False):
	path = Path(path)
	if not path.is_file():
		raise FileNotFoundError(f"Datei fehlt: {path}")
	data = json.loads(path.read_text(encoding="utf-8"))
	if expect_collection and (data.get("type") != "FeatureCollection"
		or not isinstance(data.get("features"), list)):
		raise ValueError(f"Ungültige GeoJSON FeatureCollection: {path}")
	return data


def polygon_from_feature(feature, project, *, label):
	geometry = feature.get("geometry")
	if not geometry:
		raise ValueError(f"Fehlende Geometrie: {label}")
	geom = transform(project, shape(geometry))
	if not geom.is_valid:
		geom = polygonal_part(make_valid(geom))
	if geom is None or geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon") or geom.area <= 0:
		raise ValueError(f"Keine gültige Polygonfläche: {label}")
	return geom


def cadastral_key(properties):
	kgez = str(properties.get("kgez") or "").strip()
	gnr = str(properties.get("gnr") or "").strip()
	return (kgez.zfill(5), gnr) if kgez and gnr else None


def read_kataster_masks(kataster_dir, clip, manifest):
	"""Vereinigt doppelte Tilefragmente; nur die Kern-getroffenen Grundstücke."""
	kataster_dir = Path(kataster_dir)
	report = read_json(kataster_dir / "kataster_bericht.json")
	if report.get("zoom") != 16:
		raise ValueError("Katasterdaten müssen von Zoomstufe 16 stammen")
	bbox = report.get("bbox_lon_lat")
	if not isinstance(bbox, list) or len(bbox) != 4 or any(
		abs(float(a) - float(b)) > 1e-8 for a, b in zip(bbox, manifest["bbox_lon_lat"])
	):
		raise ValueError("FMZK und Kataster stammen aus verschiedenen Testausschnitten")
	parcels = read_json(kataster_dir / "kataster_grundstuecke.geojson", expect_collection=True)
	usages = read_json(kataster_dir / "kataster_nfl_ausschnitt.geojson", expect_collection=True)
	if (len(parcels["features"]) != report.get("grundstuecke")
		or not parcels["features"] or not usages["features"]):
		raise ValueError("Kataster-GeoJSONs und Katasterbericht passen nicht zusammen")
	to_local = Transformer.from_crs("EPSG:4326", "EPSG:31256", always_xy=True).transform
	parcel_ids = set()
	for item in parcels["features"]:
		key = cadastral_key(item.get("properties") or {})
		if key is None or key in parcel_ids:
			raise ValueError(f"Fehlende oder doppelte Grundstücks-ID: {key}")
		parcel_ids.add(key)
	street_parts = []
	other_parts = []
	repairs = 0
	observed = Counter()
	for index, item in enumerate(usages["features"]):
		props = item.get("properties") or {}
		key = cadastral_key(props)
		if key not in parcel_ids:
			raise ValueError(f"nfl-Feature {index} gehört nicht zu einem untersuchten Grundstück: {key}")
		code = props.get("ns")
		if not str(code).isdigit():
			raise ValueError(f"Unbekannter nfl-Nutzungscode in Feature {index}: {code}")
		code = int(code)
		if props.get("vollstaendig") is not False:
			raise ValueError(f"nfl-Feature {index} erwartet Ausschnittsgeometrie (vollstaendig=false)")
		unprojected = shape(item["geometry"])
		if not unprojected.is_valid:
			repairs += 1
		geom = polygon_from_feature(item, to_local, label=f"nfl #{index}")
		geom = geom.intersection(clip)
		if geom.is_empty or geom.area <= 0:
			continue
		observed[code] += 1
		if code in STREET_USAGE_CODES:
			street_parts.append(geom)
		else:
			other_parts.append(geom)
	if not street_parts or not other_parts:
		raise ValueError("nfl benötigt sowohl Straßenverkehrs- als auch sonstige Nutzungsflächen")
	street = union_all(street_parts)
	other = union_all(other_parts)
	if not street.is_valid or not other.is_valid:
		raise ValueError("nfl-Vereinigung ergab ungültige Geometrie")
	return street, other, {
		"nfl_fragmente": len(usages["features"]),
		"nfl_nutzungen_fragmente": dict(sorted(observed.items())),
		"nfl_reparaturen": repairs,
		"betroffene_grundstuecke": len(parcel_ids),
		"strassenmaske_m2": street.area,
		"sonstige_maske_m2": other.area,
		"nfl_gegenseitige_ueberlagerung_m2": street.intersection(other).area,
	}


def classify_fmzk(features, street, other, *, minimum_share=DEFAULT_MIN_SHARE):
	"""Jede FMZK-Fläche genau einmal und unzerschnitten zurückgeben."""
	if not (0.5 < minimum_share <= 1):
		raise ValueError("--min-strassenanteil muss größer als 0,5 und höchstens 1 sein")
	classified = []
	identifiers = set()
	covered = street.union(other)
	for fid, code, label, geom in features:
		if fid in identifiers:
			raise ValueError(f"Doppelte FMZK-FID: {fid}")
		identifiers.add(fid)
		area = geom.area
		street_area = geom.intersection(street).area
		other_area = geom.intersection(other).area
		street_ratio = min(1.0, street_area / area)
		other_ratio = min(1.0, other_area / area)
		# Kachel-Duplikate zählen durch räumliche Vereinigung nur einmal.
		coverage = geom.intersection(covered).area / area
		unknown_ratio = max(0.0, 1.0 - coverage)
		if code in CORE_CODES:
			target, decision = "strassenraum", "fmzk_kern"
		elif street_ratio >= minimum_share and other_ratio <= 1.0 - minimum_share:
			target, decision = "strassenraum", "nfl_95_65_hohe_deckung"
		elif street_area > 0:
			target, decision = "uebrige", "teilweise_strassenlage_pruefen"
		elif unknown_ratio > 0.05:
			target, decision = "uebrige", "kataster_teilweise_ohne_nutzung"
		else:
			target, decision = "uebrige", "keine_strassenlage_nachgewiesen"
		props = {
			"fid": fid,
			"f_klasse": code,
			"f_klasse_text": label,
			"zuordnung": target,
			"grund": decision,
			"flaeche_m2": area,
			"kataster_strassenanteil_pct": round(street_ratio * 100, 3),
			"kataster_sonstige_pct": round(other_ratio * 100, 3),
			"kataster_ohne_nutzung_pct": round(unknown_ratio * 100, 3),
			"pruefhinweis": ("kern_abweichung_zum_kataster"
				if code in CORE_CODES and (street_ratio < 0.90 or other_ratio > 0.10)
				else ""),
		}
		classified.append((target, props, geom))
	return classified


def original_attributes(source, fids):
	"""Nur die für Wiederauffinden und Prüfung nützlichen Originalattribute."""
	source = Path(source)
	uri = "file:" + quote(str(source.resolve()), safe="/") + "?mode=ro"
	with closing(sqlite3.connect(uri, uri=True)) as conn:
		fields = {row[1] for row in conn.execute('PRAGMA table_info("fmzk")')}
		optional = [name for name in ("FMZK_ID", "KLASSE_SUB", "KLASSE_SUB_TEXT", "BEZUG") if name in fields]
		if not optional:
			return {}
		selected = ', '.join('"' + name + '"' for name in optional)
		return {row[0]: dict(zip(optional, row[1:])) for row in conn.execute(
			f'SELECT "id", {selected} FROM "fmzk"') if row[0] in fids}


def write_two_geojson(classified, source, output_dir, *, mask_stats, minimum_share):
	output_dir = Path(output_dir)
	# Validieren, bevor bestehende Dateien verändert werden.
	identifiers = [props["fid"] for _, props, _ in classified]
	if len(identifiers) != len(set(identifiers)):
		raise ValueError("Duplikate in FMZK-Zuordnung")
	originals = original_attributes(source, set(identifiers))
	to_wgs84 = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform
	collections = {"strassenraum": [], "uebrige": []}
	counts = Counter()
	areas = Counter()
	decisions = Counter()
	for target, props, geom in classified:
		full_properties = dict(props)
		full_properties.update({k.lower(): v for k, v in originals.get(props["fid"], {}).items()})
		collections[target].append({
			"type": "Feature", "properties": full_properties,
			"geometry": mapping(transform(to_wgs84, geom)),
		})
		counts[target] += 1
		areas[target] += geom.area
		decisions[props["grund"]] += 1
	if counts.total() != len(classified):
		raise ValueError("Die FMZK-Flächen sind nicht vollständig zugeordnet")
	output_dir.mkdir(parents=True, exist_ok=True)
	files = {
		"strassenraum": output_dir / "fmzk_strassenraum.geojson",
		"uebrige": output_dir / "fmzk_uebrige_flaechen.geojson",
	}
	for category, path in files.items():
		path.write_text(json.dumps({"type": "FeatureCollection", "features": collections[category]},
			ensure_ascii=False) + "\n", encoding="utf-8")
	report = {
		"hinweis": "Vorläufige GIS-Zuordnung, kein Nachweis öffentlicher Widmung. 'Uebrige' enthält auch ungeklärte Straßenraumkandidaten.",
		"quelle_fmzk": str(source),
		"zeitpunkt": datetime.now(timezone.utc).isoformat(),
		"regel": "Kernklassen 21/23/24/25/33/39 immer Straßenraum; sonst ganze FMZK-Polygone bei hoher Deckung mit nfl 95/65; bei Widersprüchen konservativ übrige.",
		"strassenraum_regel_version": STREET_CLASSIFICATION_VERSION,
		"kern_klassen": sorted(CORE_CODES),
		"min_strassenanteil": minimum_share,
		"dateien": {k: str(v) for k, v in files.items()},
		"fmzk_features_gesamt": len(classified),
		"features": dict(counts),
		"flaeche_m2": dict(areas),
		"entscheidungen": dict(decisions),
		"kataster": mask_stats,
	}
	(output_dir / "fmzk_aufteilung_bericht.json").write_text(
		json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	return report


def run(source=DEFAULT_SOURCE, kataster=DEFAULT_KATASTER, output=DEFAULT_OUTPUT,
	*, min_share=DEFAULT_MIN_SHARE):
	features, manifest, clip, _ = load_polygons(source)
	street, other, statistics = read_kataster_masks(kataster, clip, manifest)
	classified = classify_fmzk(features, street, other, minimum_share=min_share)
	report = write_two_geojson(classified, source, output,
		mask_stats=statistics, minimum_share=min_share)
	print(f"FMZK-Flächen: {report['fmzk_features_gesamt']}")
	for category in ("strassenraum", "uebrige"):
		print(f"  {category:13s} {report['features'].get(category, 0):5d} Flächen, "
			f"{report['flaeche_m2'].get(category, 0):.2f} m²")
	print(f"  Prüffälle: {report['entscheidungen'].get('teilweise_strassenlage_pruefen', 0)}")
	print(f"Ausgabe: {Path(output).resolve()}")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
	parser.add_argument("--kataster-dir", type=Path, default=DEFAULT_KATASTER)
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
	parser.add_argument("--min-strassenanteil", type=float, default=DEFAULT_MIN_SHARE)
	args = parser.parse_args()
	try:
		run(args.source, args.kataster_dir, args.out_dir, min_share=args.min_strassenanteil)
	except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
