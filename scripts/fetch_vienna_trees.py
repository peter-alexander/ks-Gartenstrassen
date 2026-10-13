#!/usr/bin/env python3
"""Lädt Wiener Baumkataster nur für den FMZK-Testbereich + Kronen-Randbereich.

Bewusst eigenständiges Modul für Datenbeschaffung. WFS-GeoJSON wird roh
gespeichert und anschließend von build_canopy_circles.py ausgewertet.
Keine Änderung an der Straßenraum- oder Überschirmungsberechnung.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pyproj import Transformer

from scripts.fmzk_source import load_polygons

SERVICE = "https://data.wien.gv.at/daten/geo"
TYPE_NAME = "ogdwien:BAUMKATOGD"
DEFAULT_FMZK = Path("data/processed/fmzk_test.gpkg")
DEFAULT_OUTPUT = Path("data/processed/baumkronen")
DEFAULT_PADDING_M = 35


def build_request_bbox(area, *, padding_m=DEFAULT_PADDING_M):
	if not (25 <= padding_m <= 100):
		raise ValueError("Kronen-Randbereich muss 25–100 m betragen")
	to_mercator = Transformer.from_crs("EPSG:31256", "EPSG:3857", always_xy=True).transform
	from shapely.ops import transform
	envelope = transform(to_mercator, area.buffer(padding_m))
	return envelope.bounds


def build_wfs_url(bbox, *, max_features=2000):
	if not (0 < max_features <= 20000):
		raise ValueError("maxFeatures muss zwischen 1 und 20000 liegen")
	if len(bbox) != 4 or not bbox[0] < bbox[2] or not bbox[1] < bbox[3]:
		raise ValueError("Ungültige BBOX")
	params = [
		("service", "WFS"), ("request", "GetFeature"),
		("version", "1.1.0"), ("typeName", TYPE_NAME),
		("outputFormat", "json"), ("srsName", "EPSG:4326"),
		("bbox", ",".join(map(str, bbox)) + ",EPSG:3857"),
		("maxFeatures", max_features),
	]
	return SERVICE + "?" + urlencode(params)


def validate_result(data, bbox, *, max_features):
	if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
		raise ValueError("WFS lieferte keine GeoJSON-FeatureCollection")
	features = data.get("features")
	if not isinstance(features, list):
		raise ValueError("WFS hat keine Featureliste geliefert")
	if not features:
		raise ValueError("WFS liefert keine Bäume im Testbereich; BBOX oder Dienst prüfen")
	if len(features) >= max_features:
		raise ValueError(f"WFS-Limit {max_features} erreicht; Teilmenge NICHT als vollständig exportieren")
	to_mercator = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform
	outside = 0
	valid = 0
	for item in features:
		geom = item.get("geometry") or {}
		coordinates = geom.get("coordinates") or []
		if geom.get("type") != "Point" or len(coordinates) < 2:
			raise ValueError("Baumkataster-WFS liefert unerwartete Nicht-Punktgeometrien")
		lon, lat = coordinates[:2]
		if not (isinstance(lon, (float, int)) and isinstance(lat, (float, int))
			and 10 <= lon <= 20 and 45 <= lat <= 50):
			raise ValueError("WFS-Ausgabe nicht in erwartetem EPSG:4326 (Wien)")
		x, y = to_mercator(lon, lat)
		valid += 1
		if not (bbox[0] - 5 <= x <= bbox[2] + 5
			and bbox[1] - 5 <= y <= bbox[3] + 5):
			outside += 1
	if outside or not valid:
		raise ValueError(f"{outside} WFS-Punkte außerhalb des angeforderten BBOX-Ausschnitts")
	return len(features)


def run(fmzk=DEFAULT_FMZK, output=DEFAULT_OUTPUT, *, padding_m=DEFAULT_PADDING_M,
	max_features=2000, offline=False, refresh=False):
	if offline and refresh:
		raise ValueError("--offline und --refresh schließen sich aus")
	_, manifest, clip, _ = load_polygons(fmzk)
	bbox = build_request_bbox(clip, padding_m=padding_m)
	url = build_wfs_url(bbox, max_features=max_features)
	output = Path(output)
	raw_path = output / "baumkataster_wfs.geojson"
	if raw_path.exists() and not refresh:
		raw = raw_path.read_bytes()
		origin = "lokaler_cache"
	elif offline:
		raise FileNotFoundError(f"Offline-Cache fehlt: {raw_path}")
	else:
		req = Request(url, headers={
			"User-Agent": "ks-Gartenstrassen/1.0 (lokale GIS-Analyse)",
			"Accept": "application/json",
		})
		with urlopen(req, timeout=40) as resp:
			raw = resp.read(20_000_001)
			if len(raw) > 20_000_000:
				raise ValueError("WFS-Antwort zu groß (>20 MB); bitte kleineres Testgebiet")
		origin = "wfs_heruntergeladen"
	data = json.loads(raw.decode("utf-8-sig"))
	count = validate_result(data, bbox, max_features=max_features)
	if origin == "wfs_heruntergeladen":
		output.mkdir(parents=True, exist_ok=True)
		tmp = raw_path.with_suffix(".tmp")
		tmp.write_bytes(raw)
		tmp.replace(raw_path)
	report = {
		"stand_utc": datetime.now(timezone.utc).isoformat(),
		"quelle": SERVICE, "typeName": TYPE_NAME,
		"query": url, "bbox_3857": bbox,
		"fmzk_bbox_lon_lat": manifest["bbox_lon_lat"],
		"padding_m": padding_m, "anzahl_baeume": count,
		"datei": str(raw_path), "sha256": hashlib.sha256(raw).hexdigest(),
		"origin": origin,
		"hinweis": "WFS-Datei bleibt roh; für Messung zuerst Kronenkreise erzeugen. BBOX im WFS EPSG:3857, Ausgabe EPSG:4326.",
	}
	output.mkdir(parents=True, exist_ok=True)
	(output / "baumkataster_wfs_bericht.json").write_text(
		json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	print(f"Baumkataster: {count} Punkte ({origin})")
	print(f"GeoJSON: {raw_path}")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--fmzk", type=Path, default=DEFAULT_FMZK)
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
	parser.add_argument("--padding-m", type=float, default=DEFAULT_PADDING_M)
	parser.add_argument("--max-features", type=int, default=2000)
	parser.add_argument("--offline", action="store_true")
	parser.add_argument("--refresh", action="store_true")
	args = parser.parse_args()
	try:
		run(args.fmzk, args.out_dir, padding_m=args.padding_m,
			max_features=args.max_features, offline=args.offline, refresh=args.refresh)
	except (OSError, ValueError, TypeError, KeyError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
