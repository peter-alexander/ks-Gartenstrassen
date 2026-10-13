#!/usr/bin/env python3
"""Kleinen FMZK-WFS-Testausschnitt abrufen und auf Vollstaendigkeit pruefen."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from io import BytesIO

WFS_URL = "https://data.wien.gv.at/daten/geo"
LAYERS = {
	"verkehr1": "ogdwien:FMZKVERKEHR1OGD",
	"verkehr2": "ogdwien:FMZKVERKEHR2OGD",
}
DEFAULT_BBOX = "16.361012,48.221226,16.366948,48.224902"


def parse_bbox(raw):
	try:
		west, south, east, north = (float(value) for value in raw.split(","))
	except (ValueError, TypeError) as exc:
		raise ValueError("BBOX benötigt west,süd,ost,nord in EPSG:4326") from exc
	if not (west < east and south < north):
		raise ValueError("Ungültige BBOX: Ost/Nord müssen größer als West/Süd sein")
	if not (16.0 < west < east < 17.0 and 48.0 < south < north < 49.0):
		raise ValueError("Der erste Prototyp ist auf einen Testausschnitt in Wien beschränkt")
	if (east - west) * (north - south) > 0.0002:
		raise ValueError("Testgebiet zu groß für einen einzelnen WFS-Abruf; bitte verkleinern")
	return (west, south, east, north)


def get_url(layer, bbox, output_format, max_features):
	params = {
		"service": "WFS",
		"request": "GetFeature",
		"version": "1.0.0",  # EPSG:4326 in WFS 1.0: x=lon, y=lat
		"typeName": layer,
		"srsName": "EPSG:4326",
		"bbox": ",".join(str(n) for n in bbox) + ",EPSG:4326",
		"maxFeatures": str(max_features),
		"outputFormat": output_format,
	}
	return WFS_URL + "?" + urllib.parse.urlencode(params)


def download(url):
	request = urllib.request.Request(url, headers={"User-Agent": "ks-Gartenstrassen/0.1 (Forschungsprototyp; kleine WFS-Testausschnitte)"})
	try:
		with urllib.request.urlopen(request, timeout=60) as response:
			return response.read()
	except urllib.error.HTTPError as exc:
		detail = exc.read(600).decode("utf-8", errors="replace")
		raise RuntimeError(f"WFS HTTP {exc.code}: {detail}") from exc


def validate_geojson(raw, max_features):
	try:
		data = json.loads(raw)
	except (UnicodeDecodeError, json.JSONDecodeError) as exc:
		raise ValueError("WFS lieferte kein gültiges GeoJSON (evtl. ServiceException/XML)") from exc
	if data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
		raise ValueError("WFS-Antwort enthält keine GeoJSON FeatureCollection")
	features = data["features"]
	if not features:
		raise ValueError("Keine Objekte im Testgebiet: BBOX und Layer kontrollieren")
	if len(features) >= max_features:
		raise ValueError(f"{len(features)} Features erreichen maxFeatures={max_features}; Ausschnitt verkleinern")
	for field in ("totalFeatures", "numberMatched"):
		try:
			total = int(data[field])
		except (KeyError, TypeError, ValueError):
			continue
		if total > len(features):
			raise ValueError(f"Unvollständige WFS-Antwort: {field}={total}, geliefert={len(features)}")
	for feature in features:
		if feature.get("type") != "Feature" or not feature.get("geometry"):
			raise ValueError("WFS-Antwort enthält ungültige oder geometriefreie Features")
	return data


def summarize(data):
	features = data["features"]
	keys = sorted(set().union(*(f.get("properties", {}).keys() for f in features)))
	counts = Counter(str(f.get("properties", {}).get("F_KLASSE", "(fehlend)")) for f in features)
	return {"feature_count": len(features), "properties": keys, "f_klasse_counts": dict(sorted(counts.items()))}


def validate_shape_zip(raw):
	try:
		with zipfile.ZipFile(BytesIO(raw)) as archive:
			files = archive.namelist()
			for extension in (".shp", ".shx", ".dbf"):
				if not any(name.lower().endswith(extension) for name in files):
					raise ValueError(f"Shapefile-ZIP ohne {extension}: {files}")
	except zipfile.BadZipFile as exc:
		raise ValueError("WFS lieferte kein gültiges Shapefile-ZIP") from exc


def run(bbox, output_dir, max_features, file_format):
	# Zuerst sämtliche Abfragen validieren, erst danach Dateien schreiben.
	results = {}
	for short_name, layer in LAYERS.items():
		url = get_url(layer, bbox, "json", max_features)
		print(f"Abruf {short_name}: {url}", flush=True)
		data = validate_geojson(download(url), max_features)
		shape_bytes = None
		if file_format in ("shape-zip", "both"):
			shape_url = get_url(layer, bbox, "shape-zip", max_features)
			print(f"Shapefile-Abruf {short_name}: {shape_url}", flush=True)
			shape_bytes = download(shape_url)
			validate_shape_zip(shape_bytes)
		results[short_name] = (data, shape_bytes, url)

	output_dir.mkdir(parents=True, exist_ok=True)
	manifest = {"retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
		"wfs_version": "1.0.0", "crs": "EPSG:4326", "bbox_lon_lat": bbox,
		"max_features": max_features, "layers": {}}
	for name, (data, shape_bytes, url) in results.items():
		if file_format in ("geojson", "both"):
			(output_dir / f"fmzk_{name}.geojson").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
		if shape_bytes is not None:
			(output_dir / f"fmzk_{name}.zip").write_bytes(shape_bytes)
		manifest["layers"][name] = {"wfs_layer": LAYERS[name], "source_url": url, **summarize(data)}
		print(f"{name}: {manifest['layers'][name]['feature_count']} Features, F_KLASSE: {manifest['layers'][name]['f_klasse_counts']}")
	(output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	print(f"Ergebnis: {output_dir.resolve()}")


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--bbox", default=DEFAULT_BBOX, help="west,süd,ost,nord (EPSG:4326)")
	parser.add_argument("--out-dir", default="data/raw", type=Path)
	parser.add_argument("--max-features", default=5000, type=int)
	parser.add_argument("--format", choices=("geojson", "shape-zip", "both"), default="geojson")
	args = parser.parse_args()
	if args.max_features < 1 or args.max_features > 10000:
		parser.error("max-features muss zwischen 1 und 10000 liegen")
	try:
		run(parse_bbox(args.bbox), args.out_dir, args.max_features, args.format)
	except (ValueError, RuntimeError, urllib.error.URLError, TimeoutError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
