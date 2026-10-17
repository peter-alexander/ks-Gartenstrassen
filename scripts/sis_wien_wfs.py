"""Wienweiter SIS-WFS-Cache: kleine überlappende Requests, dann ID-Deduplikation.

Die Rohkacheln bleiben für Wiederholungsläufe unverändert erhalten.
Kein Feature wird räumlich an den Request-Bounds abgeschnitten.
"""
import argparse
import hashlib
import json
import lzma
from pathlib import Path
import sqlite3
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from shapely.geometry import box

from scripts.wienwide_grid import load_aoi

SERVICE = "https://data.wien.gv.at/daten/geo"
LAYER = "ogdwien:SISBELAGOGD"
CORE_M = 1700
HALO_M = 100
REQUEST_M = CORE_M + 2 * HALO_M
MAX_BYTES = 32 * 1024 * 1024
MAX_FEATURES = 10000


def tiles(aoi):
	"""Nur AOI-schneidende 1.700-m-Kerne; Requests sind 1.900 m breit."""
	metric = aoi
	x0, y0, x1, y1 = metric.bounds
	import math
	for ix in range(math.floor(x0 / CORE_M), math.ceil(x1 / CORE_M)):
		for iy in range(math.floor(y0 / CORE_M), math.ceil(y1 / CORE_M)):
			x, y = ix * CORE_M, iy * CORE_M
			core = box(x, y, x + CORE_M, y + CORE_M)
			if not metric.intersects(core):
				continue
			yield f"x{ix:+06d}_y{iy:+06d}", (
				x - HALO_M, y - HALO_M, x + CORE_M + HALO_M, y + CORE_M + HALO_M)


def request_url(bounds):
	params = [
		("service", "WFS"), ("request", "GetFeature"), ("version", "1.1.0"),
		("typeName", LAYER), ("srsName", "EPSG:4326"),
		("outputFormat", "json"),
		("bbox", ",".join(str(v) for v in bounds) + ",EPSG:31256"),
	]
	return SERVICE + "?" + urlencode(params)


def validate(raw, *, tile):
	doc = json.loads(raw)
	if doc.get("type") != "FeatureCollection" or not isinstance(doc.get("features"), list):
		raise ValueError(f"{tile}: WFS-Antwort ist keine GeoJSON-FeatureCollection")
	features = doc["features"]
	if len(features) >= MAX_FEATURES:
		raise ValueError(f"{tile}: {len(features)} Features – mögliche Serverbegrenzung")
	for field in ("numberOfFeatures", "numberMatched"):
		value = doc.get(field)
		if value is not None and str(value).isdigit() and int(value) != len(features):
			raise ValueError(f"{tile}: {field}={value}, geliefert={len(features)}")
	for idx, feature in enumerate(features):
		if feature.get("type") != "Feature":
			raise ValueError(f"{tile}: Feature {idx} ungültig")
		properties = feature.get("properties")
		if not isinstance(properties, dict) or any(k not in properties for k in
				("TYPE", "BELAG", "BELAG_TXT", "SIS_ID")):
			raise ValueError(f"{tile}: Feature {idx} ohne benötigte SIS-Attribute")
		if feature.get("geometry") is None:
			raise ValueError(f"{tile}: Feature {idx} ohne Geometrie")
	return doc


def fetch_tile(name, bounds, cache):
	url = request_url(bounds)
	path = cache / f"{name}.geojson.xz"
	meta_path = cache / f"{name}.json"
	expected = {"url": url, "bbox_31256": list(bounds), "layer": LAYER,
		"compression": "xz-lzma2", "preset": 6}
	if path.exists() or meta_path.exists():
		if not path.exists() or not meta_path.exists():
			raise ValueError(f"{name}: unvollständige Cache-Dateien")
		metadata = json.loads(meta_path.read_text(encoding="utf-8"))
		if any(metadata.get(k) != v for k,v in expected.items()):
			raise ValueError(f"{name}: Cache-Abfrageparameter geändert")
		compressed = path.read_bytes()
		if hashlib.sha256(compressed).hexdigest() != metadata.get("sha256_xz"):
			raise ValueError(f"{name}: Cache-Prüfsumme falsch")
		raw = lzma.decompress(compressed, format=lzma.FORMAT_XZ)
		if hashlib.sha256(raw).hexdigest() != metadata.get("sha256_raw"):
			raise ValueError(f"{name}: dekomprimierte Cache-Prüfsumme falsch")
		doc = validate(raw, tile=name)
		if len(doc["features"]) != metadata.get("features"):
			raise ValueError(f"{name}: Cache-Featurezahl falsch")
		return path, len(doc["features"]), False
	req = Request(url, headers={"User-Agent": "ks-Gartenstrassen/sis-wien-tiles-v1",
		"Accept": "application/json"})
	with urlopen(req, timeout=150) as response:
		raw = response.read(MAX_BYTES + 1)
	if len(raw) > MAX_BYTES:
		raise ValueError(f"{name}: Antwort über 32 MiB, Kachel muss verkleinert werden")
	doc = validate(raw, tile=name)
	compressed = lzma.compress(raw, format=lzma.FORMAT_XZ, preset=6)
	temp = path.with_suffix(".xz.download")
	if temp.exists():
		raise FileExistsError(temp)
	cache.mkdir(parents=True, exist_ok=True)
	try:
		with temp.open("xb") as target:
			target.write(compressed)
		temp.replace(path)
		meta = {**expected, "sha256_raw": hashlib.sha256(raw).hexdigest(),
			"sha256_xz": hashlib.sha256(compressed).hexdigest(),
			"features": len(doc["features"])}
		meta_temp = meta_path.with_suffix(".json.tmp")
		meta_temp.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
			encoding="utf-8")
		meta_temp.replace(meta_path)
	except BaseException:
		temp.unlink(missing_ok=True)
		raise
	return path, len(doc["features"]), True


def feature_identity(feature):
	"""Nur eine quellseitige Feature-ID, niemals die GIP-EDGE-object_id."""
	props = feature["properties"]
	oid = props.get("OBJECTID")
	if oid is not None and str(oid).strip():
		return "OBJECTID:" + str(oid)
	identifier = feature.get("id")
	if identifier is not None and str(identifier).strip():
		return "WFS_ID:" + str(identifier)
	raise ValueError("SIS-Feature ohne OBJECTID/WFS-ID: sichere Deduplikation unmöglich")


def merge_cached(cached, output):
	"""Deduplizieren BEVOR das GeoJSON zusammengefügt wird; keine Featureliste im RAM."""
	output = Path(output)
	if not output.name.endswith(".geojson.xz"):
		raise ValueError("Zusammengeführte Daten müssen .geojson.xz sein")
	if output.exists():
		raise FileExistsError(output)
	temp = output.with_suffix(".tmp")
	if temp.exists():
		raise FileExistsError(temp)
	seen_db = output.with_suffix(".dedup.tmp.sqlite")
	if seen_db.exists():
		raise FileExistsError(seen_db)
	unique = duplicates = 0
	try:
		with sqlite3.connect(seen_db) as seen, lzma.open(temp, "wt", encoding="utf-8", preset=6) as out:
			seen.execute("CREATE TABLE features(id TEXT PRIMARY KEY,signature TEXT)")
			out.write('{"type":"FeatureCollection","features":[')
			for tile_file in cached:
				with lzma.open(tile_file, "rb") as source:
					doc = validate(source.read(MAX_BYTES + 1), tile=tile_file.name)
				for feature in doc["features"]:
					key = feature_identity(feature)
					signature = hashlib.sha256(json.dumps(
						{"properties": feature["properties"],"geometry": feature["geometry"]},
						sort_keys=True, separators=(",",":"), ensure_ascii=False
					).encode("utf-8")).hexdigest()
					previous = seen.execute(
						"SELECT signature FROM features WHERE id=?", (key,)).fetchone()
					if previous:
						if previous[0] != signature:
							raise ValueError(f"Quell-ID {key}: widersprüchliche Dubletten")
						duplicates += 1
						continue
					seen.execute("INSERT INTO features VALUES (?,?)", (key, signature))
					if unique:
						out.write(",")
					out.write(json.dumps(feature, ensure_ascii=False, separators=(",",":")))
					unique += 1
			out.write("]}\n")
		temp.replace(output)
	finally:
		temp.unlink(missing_ok=True)
		seen_db.unlink(missing_ok=True)
	return {"eindeutige_features":unique,"entfernte_dubletten":duplicates}


def run(aoi_path, cache, output=None, *, import_root=None):
	cache = Path(cache)
	output = Path(output) if output is not None else None
	import_root = Path(import_root) if import_root is not None else None
	if output is None and import_root is None:
		raise ValueError("Entweder --out oder --import-root angeben")
	aoi = load_aoi(aoi_path)  # EPSG:31256
	grid = list(tiles(aoi))
	if not grid:
		raise ValueError("Keine Wien-Kacheln im Untersuchungsgebiet")
	files = []
	fetched = 0
	for i,(name,bounds) in enumerate(grid,1):
		path, count, downloaded = fetch_tile(name,bounds,cache)
		files.append(path)
		fetched += int(downloaded)
		if import_root is not None:
			from scripts.sis_belagsflaechen import build
			destination = import_root / name
			if not (destination / "sis.sqlite").is_file():
				build(path, destination)
		print(f"SIS WFS {i}/{len(grid)}: {name}: {count} Features "
			f"({'neu' if downloaded else 'Cache'})", flush=True)
	result = merge_cached(files, output) if output is not None else {}
	report = {**result,"tiles":len(files),"neu_geladen":fetched,
		"aus_cache":len(files)-fetched,"wfs_kachel_m":REQUEST_M,
		"ueberlappung_zwischen_kacheln_m":2*HALO_M,
		"cache":str(cache),"merged":str(output) if output else None,
		"import_root":str(import_root) if import_root else None}
	if output is not None:
		output.with_suffix(".bericht.json").write_text(
			json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
	return report


def main():
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("--aoi",type=Path,required=True)
	p.add_argument("--cache",type=Path,default=Path("data/raw/sis-wien-tiles"))
	p.add_argument("--out",type=Path,
		help="Optionales dedupliziertes Gesamt-GeoJSON (komprimiert)")
	p.add_argument("--import-root",type=Path,
		help="Jede gecachte XZ-Kachel sofort einzeln in SIS-SQLite importieren")
	a = p.parse_args()
	print(json.dumps(run(a.aoi,a.cache,a.out,import_root=a.import_root),ensure_ascii=False,indent=2))


if __name__ == "__main__":
	main()
