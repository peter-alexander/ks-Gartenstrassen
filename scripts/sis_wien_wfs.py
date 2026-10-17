"""Wienweiter SIS-WFS-Cache: kleine überlappende Requests, dann ID-Deduplikation.

Die Rohkacheln bleiben für Wiederholungsläufe unverändert erhalten.
Kein Feature wird räumlich an den Request-Bounds abgeschnitten.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from shapely.geometry import box, shape
from shapely.ops import transform
from pyproj import Transformer

from scripts.wienwide_grid import load_aoi

SERVICE = "https://data.wien.gv.at/daten/geo"
LAYER = "ogdwien:SISBELAGOGD"
TO_METRIC = Transformer.from_crs("EPSG:4326", "EPSG:31256", always_xy=True).transform
CORE_M = 1850
HALO_M = 25
REQUEST_M = CORE_M + 2 * HALO_M
MAX_BYTES = 32 * 1024 * 1024
MAX_FEATURES = 10000


def tiles(aoi):
	"""Nur AOI-schneidende 1.850-m-Kerne; Requests sind 1.900 m breit."""
	metric = transform(TO_METRIC, aoi)
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
	path = cache / f"{name}.geojson"
	meta_path = cache / f"{name}.json"
	expected = {"url": url, "bbox_31256": list(bounds), "layer": LAYER}
	if path.exists() or meta_path.exists():
		if not path.exists() or not meta_path.exists():
			raise ValueError(f"{name}: unvollständige Cache-Dateien")
		metadata = json.loads(meta_path.read_text(encoding="utf-8"))
		if any(metadata.get(k) != v for k,v in expected.items()):
			raise ValueError(f"{name}: Cache-Abfrageparameter geändert")
		raw = path.read_bytes()
		if hashlib.sha256(raw).hexdigest() != metadata.get("sha256"):
			raise ValueError(f"{name}: Cache-Prüfsumme falsch")
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
	temp = path.with_suffix(".download")
	if temp.exists():
		raise FileExistsError(temp)
	cache.mkdir(parents=True, exist_ok=True)
	try:
		with temp.open("xb") as target:
			target.write(raw)
		temp.replace(path)
		meta = {**expected, "sha256": hashlib.sha256(raw).hexdigest(),
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
	props = feature["properties"]
	sis = props.get("SIS_ID")
	if sis is not None and str(sis).strip():
		return "SIS_ID:" + str(sis)
	identifier = feature.get("id")
	if identifier is not None and str(identifier).strip():
		return "WFS_ID:" + str(identifier)
	raise ValueError("Feature ohne SIS_ID und WFS-ID – keine sichere Deduplikation")


def merge_cached(cached, output):
	"""Deduplizieren BEVOR das GeoJSON zusammengefügt wird; keine Featureliste im RAM."""
	output = Path(output)
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
		with sqlite3.connect(seen_db) as seen, temp.open("x", encoding="utf-8") as out:
			seen.execute("CREATE TABLE features(id TEXT PRIMARY KEY,signature TEXT)")
			out.write('{"type":"FeatureCollection","features":[')
			for tile_file in cached:
				doc = validate(tile_file.read_bytes(), tile=tile_file.name)
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


def run(aoi_path, cache, output):
	cache, output = Path(cache), Path(output)
	aoi = load_aoi(aoi_path)
	grid = list(tiles(aoi))
	if not grid:
		raise ValueError("Keine Wien-Kacheln im Untersuchungsgebiet")
	files = []
	fetched = 0
	for i,(name,bounds) in enumerate(grid,1):
		path, count, downloaded = fetch_tile(name,bounds,cache)
		files.append(path)
		fetched += int(downloaded)
		print(f"SIS WFS {i}/{len(grid)}: {name}: {count} Features "
			f"({'neu' if downloaded else 'Cache'})", flush=True)
	result = merge_cached(files, output)
	report = {**result,"tiles":len(files),"neu_geladen":fetched,
		"aus_cache":len(files)-fetched,"wfs_kachel_m":REQUEST_M,
		"ueberlappung_zwischen_kacheln_m":2*HALO_M,
		"cache":str(cache),"merged":str(output)}
	output.with_suffix(".bericht.json").write_text(
		json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
	return report


def main():
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("--aoi",type=Path,required=True)
	p.add_argument("--cache",type=Path,default=Path("data/raw/sis-wien-tiles"))
	p.add_argument("--out",type=Path,required=True)
	a = p.parse_args()
	print(json.dumps(run(a.aoi,a.cache,a.out),ensure_ascii=False,indent=2))


if __name__ == "__main__":
	main()
