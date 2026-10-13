#!/usr/bin/env python3
"""Reproduzierbare FMZK-Prüfstichprobe aus der lokalen Straßenraumanalyse.

Erzeugt nur lokale GeoJSON/CSV/JSON-Dateien; keine Datenfreigabe oder
öffentliche Zurechnung. Prüfbewertungen werden nicht automatisch gesetzt.
"""

import argparse
from contextlib import closing
import csv
import json
import math
from pathlib import Path
import sqlite3
from urllib.parse import quote

from pyproj import Transformer
from shapely.geometry import shape, mapping
from shapely.ops import transform

DEFAULT_REVIEW = Path("data/processed/street_space/strassenraum_pruefung.geojson")
DEFAULT_SOURCE = Path("data/processed/fmzk_test.gpkg")
DEFAULT_OUTPUT = Path("data/processed/street_space/pruefstichprobe")

# Gruppe, Kriterien, Anzahl. Die Gruppen sind disjunkt; Klasse 59 vereint
# bewusst beide Typen der mehrseitigen Einbettung.
GROUPS = (
	("69_verschiedene_klassen", 69, ("mehrseitig_verschiedene_klassen",), None, 5),
	("69_mehrseitig", 69, ("mehrseitig",), None, 5),
	("69_einseitig", 69, ("einseitig",), None, 3),
	("69_ohne_deutlichen_kontakt", 69, ("kein_deutlicher_randkontakt",), None, 3),
	("58_am_strassenkern", 58, None, ("grenzt_an_kern",), 5),
	("59_mehrseitig", 59, ("mehrseitig", "mehrseitig_verschiedene_klassen"), None, 4),
)

CSV_FIELDS = (
	"pruef_nr", "pruefgruppe", "fid", "fmzk_id", "f_klasse", "f_klasse_text",
	"klasse_sub", "klasse_sub_text", "bezug", "flaeche_m2", "status",
	"einbettung", "abstand_kern_m", "randkontakt_m", "kontaktklassen",
	"kontakt_21_m", "kontakt_23_m", "kontakt_24_m", "kontakt_33_m",
	"kontakt_39_m", "kontakt_rand_pct", "pruefstatus", "pruefnotiz",
)


def read_review(path):
	path = Path(path)
	if not path.is_file():
		raise FileNotFoundError(f"Prüf-GeoJSON fehlt: {path}. Zuerst scripts.analyze_street_space ausführen")
	data = json.loads(path.read_text(encoding="utf-8"))
	if data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
		raise ValueError("Keine gültige GeoJSON FeatureCollection")
	features = []
	seen = set()
	# Alte Straßenraum-GeoJSONs runden m² auf zwei Stellen. Kleine Polygone
	# erscheinen daher fälschlich mit 0.00 m², obwohl die Geometrie Fläche hat.
	project = Transformer.from_crs("EPSG:4326", "EPSG:31256", always_xy=True).transform
	for feat in data["features"]:
		props = feat.get("properties") or {}
		if props.get("f_klasse") not in (58, 59, 69):
			continue
		if any(key not in props for key in ("id", "flaeche_m2", "einbettung", "status")):
			raise ValueError("Die Straßenraumanalyse ist veraltet; bitte neu berechnen")
		fid = props["id"]
		if not isinstance(fid, int) or isinstance(fid, bool) or fid in seen:
			raise ValueError(f"Ungültige oder doppelte FMZK-FID: {fid}")
		seen.add(fid)
		geom = shape(feat["geometry"])
		if geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon") or not geom.is_valid:
			raise ValueError(f"Feature {fid}: keine gültige Polygongeometrie")
		try:
			area = float(props["flaeche_m2"])
		except (TypeError, ValueError) as exc:
			raise ValueError(f"Feature {fid}: ungültiger Flächenwert") from exc
		if not math.isfinite(area) or area < 0:
			raise ValueError(f"Feature {fid}: ungültiger Flächenwert {area}")
		if area == 0:
			# Ausschließlich der gerundete Nullwert wird aus der exakten
			# Polygongeometrie nach EPSG:31256 nachberechnet.
			area = transform(project, geom).area
			if not math.isfinite(area) or area <= 0:
				raise ValueError(f"Feature {fid}: tatsächlich flächenlose Geometrie")
		clean_props = props.copy()
		clean_props["flaeche_m2"] = area
		features.append({"type": "Feature", "properties": clean_props, "geometry": feat["geometry"]})
	return features


def feature_key(feature):
	return feature["properties"]["id"]


def area_key(feature):
	props = feature["properties"]
	return (float(props["flaeche_m2"]), feature_key(feature))


def center(feature):
	point = shape(feature["geometry"]).representative_point()
	return point.x, point.y


def choose_diverse(features, amount, *, balance_subtypes=False):
	"""Kleine/mittlere/große Flächen und danach möglichst räumliche Streuung.

	Keine Zufallszahl oder Quellreihenfolge: stabile IDs bei identischen Daten.
	"""
	if len(features) < amount:
		raise ValueError(f"Nur {len(features)} verfügbare Objekte für {amount} verlangte Beispiele")
	ordered = sorted(features, key=area_key)
	chosen = []
	used = set()

	def add(feature):
		if feature_key(feature) not in used and len(chosen) < amount:
			chosen.append(feature)
			used.add(feature_key(feature))

	# Bei Klasse 59 beide Einbettungsarten im Prüfsatz vertreten lassen.
	if balance_subtypes:
		for subtype in ("mehrseitig", "mehrseitig_verschiedene_klassen"):
			part = [item for item in ordered if item["properties"]["einbettung"] == subtype]
			if part:
				add(part[len(part) // 2])

	add(ordered[0])
	add(ordered[-1])
	if amount >= 5:
		add(ordered[len(ordered) // 2])

	if len(chosen) < amount:
		# Meteräquivalente Skalierung der Längengrade am Test-Breitengrad.
		coords = {feature_key(feature): center(feature) for feature in ordered}
		mean_lat = sum(y for x, y in coords.values()) / len(coords)
		lon_scale = math.cos(math.radians(mean_lat))

		def separation(feature):
			x, y = coords[feature_key(feature)]
			return min(
				((x - coords[feature_key(taken)][0]) * lon_scale) ** 2
				+ (y - coords[feature_key(taken)][1]) ** 2
				for taken in chosen
			)

		while len(chosen) < amount:
			remaining = [feature for feature in ordered if feature_key(feature) not in used]
			add(max(remaining, key=lambda feature: (separation(feature), -feature_key(feature))))
	return chosen


def sample_groups(features, groups=GROUPS):
	selected = []
	seen = set()
	counts = []
	for name, code, embeddings, statuses, amount in groups:
		pool = [feature for feature in features
			if feature["properties"]["f_klasse"] == code
			and (embeddings is None or feature["properties"]["einbettung"] in embeddings)
			and (statuses is None or feature["properties"]["status"] in statuses)]
		picks = choose_diverse(pool, amount, balance_subtypes=name == "59_mehrseitig")
		for feature in picks:
			if feature_key(feature) in seen:
				raise ValueError(f"Stichprobengruppen überschneiden sich bei FID {feature_key(feature)}")
			seen.add(feature_key(feature))
			selected.append((name, feature))
		counts.append({"gruppe": name, "verfuegbar": len(pool), "ausgewaehlt": len(picks),
			"min_flaeche_m2": min(float(f["properties"]["flaeche_m2"]) for f in picks),
			"max_flaeche_m2": max(float(f["properties"]["flaeche_m2"]) for f in picks)})
	return selected, counts


def lookup_original_ids(path, selected):
	"""Read-only SQLite-Lookup der FID, FMZK_ID und optionalen Originalattribute."""
	path = Path(path)
	if not path.is_file():
		raise FileNotFoundError(f"FMZK-GPKG fehlt: {path}")
	ids = [feature_key(feature) for _, feature in selected]
	if not ids:
		return {}
	uri = "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro"
	with closing(sqlite3.connect(uri, uri=True)) as conn:
		cols = {row[1] for row in conn.execute('PRAGMA table_info("fmzk")')}
		required = {"id", "F_KLASSE", "FMZK_ID"}
		if not required.issubset(cols):
			raise ValueError(f"FMZK-GPKG fehlt mindestens eine der Spalten: {sorted(required - cols)}")
		optional = [name for name in ("KLASSE_SUB", "KLASSE_SUB_TEXT", "BEZUG") if name in cols]
		fields = ["id", "F_KLASSE", "FMZK_ID"] + optional
		quoted = ", ".join(f'"{field}"' for field in fields)
		placeholders = ",".join("?" for _ in ids)
		rows = conn.execute(f'SELECT {quoted} FROM "fmzk" WHERE "id" IN ({placeholders})', ids)
		original = {row[0]: dict(zip(fields, row)) for row in rows}
	for _, feature in selected:
		fid = feature_key(feature)
		if fid not in original:
			raise ValueError(f"Die Prüf-FID {fid} fehlt im lokalen GPKG: Quellen nicht passend")
		if original[fid]["F_KLASSE"] != feature["properties"]["f_klasse"]:
			raise ValueError(f"Die Klasse von FID {fid} weicht zwischen GeoJSON und GPKG ab")
	return original


def annotation_guard(output, overwrite):
	files = ("pruefbeispiele.geojson", "pruefbeispiele_punkte.geojson",
		"pruefbeispiele.csv", "pruefbeispiele_bericht.json")
	existing = [output / name for name in files if (output / name).exists()]
	if existing and not overwrite:
		raise FileExistsError(f"Prüfstichprobe existiert bereits ({existing[0]}). "
			"Nicht überschrieben; anderen --out-dir verwenden oder --overwrite angeben")
	if overwrite and (output / "pruefbeispiele.csv").is_file():
		with (output / "pruefbeispiele.csv").open(newline="", encoding="utf-8-sig") as infile:
			for row in csv.DictReader(infile):
				if row.get("pruefstatus", "offen").strip() not in ("", "offen") or row.get("pruefnotiz", "").strip():
					raise ValueError("Die vorhandene CSV enthält manuelle Bewertungen. "
						"Bitte anderen --out-dir wählen; keine Bewertungen überschreiben")
	if overwrite and (output / "pruefbeispiele.geojson").is_file():
		data = json.loads((output / "pruefbeispiele.geojson").read_text(encoding="utf-8"))
		for feature in data.get("features", []):
			props = feature.get("properties") or {}
			if props.get("pruefstatus", "offen") not in ("", "offen") or str(props.get("pruefnotiz") or "").strip():
				raise ValueError("Das vorhandene GeoJSON enthält manuelle Bewertungen. "
					"Bitte anderen --out-dir wählen; keine Bewertungen überschreiben")


def write_sample(selected, counts, originals, review_path, source_path, output, *, overwrite=False):
	output = Path(output)
	annotation_guard(output, overwrite)
	polygon_features = []
	point_features = []
	csv_rows = []
	for nr, (group, feature) in enumerate(selected, start=1):
		props = feature["properties"].copy()
		fid = props["id"]
		original = originals[fid]
		props.update({
			"pruef_nr": nr,
			"pruefgruppe": group,
			"fid": fid,
			"fmzk_id": original["FMZK_ID"],
			"klasse_sub": original.get("KLASSE_SUB"),
			"klasse_sub_text": original.get("KLASSE_SUB_TEXT"),
			"bezug": original.get("BEZUG"),
			"pruefstatus": "offen",
			"pruefnotiz": "",
		})
		polygon_features.append({"type": "Feature", "geometry": feature["geometry"], "properties": props})
		point_features.append({"type": "Feature",
			"geometry": mapping(shape(feature["geometry"]).representative_point()),
			"properties": {"pruef_nr": nr, "pruefgruppe": group, "fid": fid,
				"fmzk_id": props["fmzk_id"], "pruefstatus": "offen"}})
		csv_rows.append({field: props.get(field) for field in CSV_FIELDS})

	report = {
		"hinweis": "Stratifizierte, bewusst nicht repräsentative Stichprobe für visuelle Prüfung. Keine Validierungsquote oder öffentliche Straßenraumzuordnung.",
		"methode": "Größenextreme und mittlere Fläche, anschließend maximale räumliche Streuung (deterministisch). Klasse 59: beide Mehrseitigkeitsarten vertreten.",
		"quelle_geojson": str(review_path),
		"quelle_gpkg": str(source_path),
		"objekte": len(selected),
		"pruefstatus_werte": ["offen", "strassenraum", "kein_strassenraum", "unklar"],
		"gruppen": counts,
		"auswahl": [{"pruef_nr": row["pruef_nr"], "pruefgruppe": row["pruefgruppe"],
			"fid": row["fid"], "fmzk_id": row["fmzk_id"], "flaeche_m2": row["flaeche_m2"]}
			for row in csv_rows],
	}
	output.mkdir(parents=True, exist_ok=True)
	(output / "pruefbeispiele.geojson").write_text(json.dumps({
		"type": "FeatureCollection", "features": polygon_features,
	}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	(output / "pruefbeispiele_punkte.geojson").write_text(json.dumps({
		"type": "FeatureCollection", "features": point_features,
	}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	with (output / "pruefbeispiele.csv").open("w", encoding="utf-8-sig", newline="") as file:
		writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
		writer.writeheader()
		writer.writerows(csv_rows)
	(output / "pruefbeispiele_bericht.json").write_text(json.dumps(report, ensure_ascii=False,
		indent=2) + "\n", encoding="utf-8")
	return report


def create_sample(review_path=DEFAULT_REVIEW, source_path=DEFAULT_SOURCE,
	output=DEFAULT_OUTPUT, *, overwrite=False):
	review_path, source_path, output = Path(review_path), Path(source_path), Path(output)
	features = read_review(review_path)
	selected, counts = sample_groups(features)
	originals = lookup_original_ids(source_path, selected)
	report = write_sample(selected, counts, originals, review_path, source_path, output,
		overwrite=overwrite)
	print(f"Prüfstichprobe: {report['objekte']} Objekte; keine automatische Straßenraum-Zuordnung")
	for group in counts:
		print(f"  {group['gruppe']:31s} {group['ausgewaehlt']:2d}/{group['verfuegbar']:3d} "
			f"(Flächen: {group['min_flaeche_m2']:.2f}–{group['max_flaeche_m2']:.2f} m²)")
	print(f"Ausgabe: {output.resolve()}")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
	parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
	parser.add_argument("--overwrite", action="store_true", help="Nur unbewertete Stichprobe überschreiben")
	args = parser.parse_args()
	try:
		create_sample(args.review, args.source, args.out_dir, overwrite=args.overwrite)
	except (ValueError, FileNotFoundError, OSError, KeyError, sqlite3.Error) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
