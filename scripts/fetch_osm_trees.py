#!/usr/bin/env python3
"""Kleiner lokaler Overpass-Adapter für Methode B (Wien + OSM).

Lädt natural=tree-Nodes und natural=tree_row-Ways aus dem FMZK-Testausschnitt
mit Kronen-Puffer. Das Rohformat ist Overpass JSON (nicht GeoJSON) und
entspricht der Datenbasis des kartensammlung-overlay-builds/baumkataster.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.error
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pyproj import Transformer
from shapely.ops import transform

from scripts.fmzk_source import load_polygons

ENDPOINTS = (
	"https://overpass.kumi.systems/api/interpreter",
	"https://overpass-api.de/api/interpreter",
)
DEFAULT_FMZK = Path("data/processed/fmzk_test.gpkg")
DEFAULT_OUT = Path("data/processed/baumkronen/osm")
DEFAULT_PADDING_M = 35
MAX_BYTES = 25_000_000


def bbox_lonlat(clip, padding_m=DEFAULT_PADDING_M):
	if not (25 <= padding_m <= 100):
		raise ValueError("OSM-Puffer muss 25–100 m betragen")
	project = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform
	min_lon, min_lat, max_lon, max_lat = transform(project, clip.buffer(padding_m)).bounds
	if not (15.5 < min_lon < max_lon < 17 and 47.5 < min_lat < max_lat < 49):
		raise ValueError("Anfrage-BBOX liegt nicht im Wiener Bereich")
	return (min_lon, min_lat, max_lon, max_lat)


def overpass_query(bbox):
	w, s, e, n = bbox
	b = ",".join(f"{v:.8f}" for v in (s, w, n, e))
	return (
		"[out:json][timeout:180];\n"
		"(\n"
		f'  node["natural"="tree"]({b});\n'
		f'  way["natural"="tree_row"]({b});\n'
		");\n"
		"out body geom qt;\n"
	)


def validate_response(document):
	if not isinstance(document, dict) or not isinstance(document.get("elements"), list):
		raise ValueError("Overpass-Antwort ist keine elements-Liste")
	if document.get("remark"):
		raise ValueError(f"Overpass hat eine Warnung oder Fehlermeldung geliefert: {str(document['remark'])[:300]}")
	elements = document["elements"]
	if not elements:
		raise ValueError("Overpass hat keine Bäume geliefert; Ergebnis auf Vollständigkeit prüfen")
	ids = set()
	counts = {"osm_tree": 0, "osm_tree_row": 0}
	for item in elements:
		if not isinstance(item, dict) or item.get("type") not in ("node", "way"):
			raise ValueError("Unbekannter Overpass-Elementtyp")
		ident = item.get("id")
		if not isinstance(ident, int) or ident <= 0 or (item["type"], ident) in ids:
			raise ValueError("Fehlende oder doppelte OSM-ID")
		ids.add((item["type"], ident))
		tags = item.get("tags") or {}
		if item["type"] == "node" and tags.get("natural") == "tree":
			if not isinstance(item.get("lon"), (int, float)) or not isinstance(item.get("lat"), (int, float)):
				raise ValueError("OSM-Baum ohne Koordinaten")
			counts["osm_tree"] += 1
		elif item["type"] == "way" and tags.get("natural") == "tree_row":
			if not isinstance(item.get("geometry"), list):
				raise ValueError("OSM-Baumreihe ohne Liniengeometrie")
			counts["osm_tree_row"] += 1
		else:
			raise ValueError("Overpass liefert nicht angeforderte natural-Tags")
	if not sum(counts.values()):
		raise ValueError("Keine brauchbaren OSM-Baumobjekte")
	return counts


def download(query):
	body = urlencode({"data": query}).encode("utf-8")
	errors = []
	for endpoint in ENDPOINTS:
		try:
			req = Request(endpoint, data=body, headers={
				"User-Agent": "ks-Gartenstrassen/1.0 (lokale Baumkronenanalyse)",
				"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
				"Accept": "application/json",
			}, method="POST")
			with urlopen(req, timeout=240) as response:
				raw = response.read(MAX_BYTES + 1)
			if len(raw) > MAX_BYTES:
				raise ValueError("OSM-Antwort überschreitet 25 MB")
			data = json.loads(raw.decode("utf-8-sig"))
			validate_response(data)
			return data, raw, endpoint
		except (OSError, ValueError, UnicodeDecodeError) as exc:
			errors.append(f"{endpoint}: {exc}")
	raise ValueError("Alle Overpass-Endpunkte fehlgeschlagen: " + "; ".join(errors))


def run(*, fmzk=DEFAULT_FMZK, output=DEFAULT_OUT, padding_m=DEFAULT_PADDING_M,
	refresh=False, offline=False):
	if refresh and offline:
		raise ValueError("--offline und --refresh schließen einander aus")
	_, manifest, clip, _ = load_polygons(fmzk)
	bbox = bbox_lonlat(clip, padding_m)
	query = overpass_query(bbox)
	output = Path(output)
	raw_file = output / "osm_baeume_overpass.json"
	metadata_file = output / "osm_baeume_overpass_bericht.json"
	if raw_file.exists() and not refresh:
		if not metadata_file.is_file():
			raise ValueError("OSM-Cache vorhanden, aber Metadaten fehlen; --refresh nutzen")
		previous = json.loads(metadata_file.read_text(encoding="utf-8"))
		if previous.get("query") != query or previous.get("gebiet_bbox_lon_lat") != manifest["bbox_lon_lat"]:
			raise ValueError("OSM-Cache gehört zu anderem Testgebiet/Puffer; --refresh nutzen")
		raw = raw_file.read_bytes()
		if hashlib.sha256(raw).hexdigest() != previous.get("sha256"):
			raise ValueError("OSM-Cache stimmt nicht mit der gespeicherten Prüfsumme überein")
		data = json.loads(raw.decode("utf-8-sig"))
		validate_response(data)
		endpoint = previous.get("endpoint")
		origin = "lokaler_cache"
	elif offline:
		raise FileNotFoundError(f"Kein gültiger OSM-Cache: {raw_file}")
	else:
		data, raw, endpoint = download(query)
		origin = "overpass_heruntergeladen"
	counts = validate_response(data)
	output.mkdir(parents=True, exist_ok=True)
	if origin == "overpass_heruntergeladen":
		tmp = raw_file.with_suffix(".tmp")
		tmp.write_bytes(raw)
		tmp.replace(raw_file)
	report = {
		"schema_version": 1,
		"stand_utc": datetime.now(timezone.utc).isoformat(),
		"quelle": "OpenStreetMap via Overpass API",
		"endpoint": endpoint, "origin": origin,
		"query": query, "bbox_lonlat_padded": bbox,
		"padding_m": padding_m,
		"gebiet_bbox_lon_lat": manifest["bbox_lon_lat"],
		"osm_elements": len(data["elements"]),
		"elementklassen": counts,
		"sha256": hashlib.sha256(raw).hexdigest(),
		"raw_json": str(raw_file),
		"hinweis": "Original-Overpass JSON. Die Baumreihen werden erst in Methode B nach der bereits in kartensammlung-overlay-builds verwendeten Strategie zu Punktpositionen.",
	}
	metadata_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
		encoding="utf-8")
	print(f"OSM: {counts['osm_tree']} Einzelbäume, {counts['osm_tree_row']} Baumreihen ({origin})")
	print(f"Rohdaten: {raw_file}")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--fmzk", type=Path, default=DEFAULT_FMZK)
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
	parser.add_argument("--padding-m", type=float, default=DEFAULT_PADDING_M)
	parser.add_argument("--refresh", action="store_true")
	parser.add_argument("--offline", action="store_true")
	args = parser.parse_args()
	try:
		run(fmzk=args.fmzk, output=args.out_dir, padding_m=args.padding_m,
			refresh=args.refresh, offline=args.offline)
	except (OSError, ValueError, TypeError, KeyError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
