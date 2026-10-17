"""SIS-Belagsflächen: reproduzierbarer GeoJSON-Pilot als V2-Straßenraumprovider.

Pilotquelle ist exakt SISBELAGOGD.json; keine Einschränkung auf Gehsteig-TYPEs.
Dieser Schritt berechnet noch keine GIP-Kanten und klassifiziert keine Entsiegelung.
Später kann ein gekachelter WFS-Adapter dieselbe Eingangsstruktur erzeugen.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from urllib.request import urlopen

from pyproj import Transformer
from shapely import union_all
from shapely.geometry import Polygon, MultiPolygon, shape
from shapely.ops import transform
from shapely.wkb import dumps

SOURCE_URL = "https://tiles.radlobby.at/Gehsteigbreiten/Testdaten/SISBELAGOGD.json"
SCHEMA = "sis-belagsflaechen-pilot-v1"
TO_METRIC = Transformer.from_crs("EPSG:4326", "EPSG:31256", always_xy=True).transform
MAX_SOURCE_BYTES = 150 * 1024 * 1024


def download_source(url, destination):
	"""Nur die vorgegebene Testquelle, begrenzter Download, niemals überschreiben."""
	if url != SOURCE_URL:
		raise ValueError("Pilot erlaubt ausschließlich die vereinbarte SIS-Testquelle")
	if destination.exists():
		raise FileExistsError(destination)
	temporary = destination.with_suffix(".download")
	if temporary.exists():
		raise FileExistsError(temporary)
	try:
		with urlopen(url, timeout=90) as source, temporary.open("xb") as target:
			amount = 0
			while chunk := source.read(1024 * 1024):
				amount += len(chunk)
				if amount > MAX_SOURCE_BYTES:
					raise ValueError("SIS-Testquelle übersteigt 150 MiB")
				target.write(chunk)
		temporary.replace(destination)
	except BaseException:
		temporary.unlink(missing_ok=True)
		raise


def read_surfaces(path):
	"""Alle Polygonfeatures mit sämtlichen TYPE-Werten, metrisch transformiert."""
	doc = json.loads(Path(path).read_text(encoding="utf-8"))
	if doc.get("type") != "FeatureCollection" or not isinstance(doc.get("features"), list):
		raise ValueError("SIS-Eingabe muss eine GeoJSON-FeatureCollection sein")
	if "crs" in doc:
		raise ValueError("GeoJSON mit explizitem CRS nicht erlaubt; EPSG:4326 erwartet")
	if not doc["features"]:
		raise ValueError("SIS-FeatureCollection ist leer")
	rows = []
	for index, feature in enumerate(doc["features"]):
		if not isinstance(feature, dict) or feature.get("type") != "Feature":
			raise ValueError(f"Feature {index}: ungültige Struktur")
		props = feature.get("properties")
		if not isinstance(props, dict) or not isinstance(props.get("TYPE"), str):
			raise ValueError(f"Feature {index}: SIS TYPE fehlt oder ist kein Text")
		geom = shape(feature.get("geometry"))
		if not isinstance(geom, (Polygon, MultiPolygon)) or geom.is_empty or not geom.is_valid:
			raise ValueError(f"Feature {index}: ungültige Polygongeometrie")
		west, south, east, north = geom.bounds
		if not (15.5 < west <= east < 17.5 and 47.5 < south <= north < 49):
			raise ValueError(f"Feature {index}: Koordinaten außerhalb Wiens / Achsen vertauscht")
		metric = transform(TO_METRIC, geom)
		if not metric.is_valid or metric.is_empty or metric.area <= 0:
			raise ValueError(f"Feature {index}: ungültige metrische Fläche")
		rows.append((index, props["TYPE"], metric))
	return rows


def build(source, output):
	"""Original unverändert übernehmen, alle Einzelbeläge und Union indizieren."""
	source, output = Path(source), Path(output)
	if output.exists():
		raise FileExistsError(f"Vorhandener Pilotordner wird nicht überschrieben: {output}")
	if not source.is_file():
		raise FileNotFoundError(source)
	rows = read_surfaces(source)
	street = union_all([geom for _, _, geom in rows])
	if not street.is_valid or street.is_empty or street.area <= 0:
		raise ValueError("SIS-Gesamtfläche ungültig")
	sha = hashlib.sha256(source.read_bytes()).hexdigest()
	output.mkdir(parents=True)
	try:
		shutil.copyfile(source, output/"SISBELAGOGD.json")
		with sqlite3.connect(output/"sis.sqlite") as db:
			db.executescript("""
				CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
				CREATE TABLE surfaces (
					id INTEGER PRIMARY KEY, type TEXT NOT NULL,
					area_m2 REAL NOT NULL, geom BLOB NOT NULL
				);
				CREATE VIRTUAL TABLE surface_index USING rtree(
					id,minx,maxx,miny,maxy
				);
				CREATE TABLE street (geom BLOB NOT NULL);
			""")
			for index, kind, geom in rows:
				db.execute("INSERT INTO surfaces VALUES (?,?,?,?)",
					(index, kind, geom.area, dumps(geom)))
				db.execute("INSERT INTO surface_index VALUES (?,?,?,?,?)",
					(index, geom.bounds[0], geom.bounds[2], geom.bounds[1], geom.bounds[3]))
			db.execute("INSERT INTO street VALUES (?)", (dumps(street),))
			for key, value in {"schema": SCHEMA, "crs": "EPSG:31256",
				"sha256": sha, "provider": "SISBELAGOGD",
				"source_url": SOURCE_URL}.items():
				db.execute("INSERT INTO metadata VALUES (?,?)", (key, value))
		counts = {}
		for _, kind, geom in rows:
			entry = counts.setdefault(kind, {"features": 0, "summierte_flaeche_m2": 0})
			entry["features"] += 1
			entry["summierte_flaeche_m2"] += geom.area
		report = {
			"schema": SCHEMA, "quelle": SOURCE_URL, "sha256": sha,
			"crs": "EPSG:31256", "features": len(rows),
			"brutto_summe_m2": sum(g.area for _, _, g in rows),
			"vereinigte_strassenbelagsflaeche_m2": street.area,
			"ueberlagerungsflaeche_m2": sum(g.area for _, _, g in rows)-street.area,
			"type_klassen": counts,
			"status": "V2-Quellpilot; keine Entsiegelungsklassifikation und keine GIP-Abschnitte",
		}
		(output/"bericht.json").write_text(
			json.dumps(report, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
		return report
	except BaseException:
		shutil.rmtree(output)
		raise


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--source-file", type=Path, help="Bereits lokal vorhandene exakt gleiche Testdatei")
	parser.add_argument("--out-dir", type=Path,
		default=Path("data/processed/sis-pilot-v2"))
	args = parser.parse_args()
	if args.source_file is None:
		cache = Path("data/raw/sis/SISBELAGOGD.json")
		cache.parent.mkdir(parents=True, exist_ok=True)
		if not cache.exists():
			download_source(SOURCE_URL, cache)
		source = cache
	else:
		source = args.source_file
	print(json.dumps(build(source, args.out_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
	main()
