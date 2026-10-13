#!/usr/bin/env python3
"""Katasterprüfung: FMZK-Straßenkern -> BEV-Grundstücke -> ganze Nutzungsbilanz.

Quelle: BEV Vector Tiles z16 (gst/nfl) und Grundstücksdetails pro Treffer.
Nur lokale Ausgaben; keine Behauptung rechtsverbindlicher Widmung.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import json
import math
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import mapbox_vector_tile
from pyproj import Transformer
from shapely import union_all
from shapely.geometry import box, mapping, shape
from shapely.ops import transform

from scripts.analyze_street_space import CORE_CODES, load_polygons

BASE = "https://kataster.bev.gv.at"
DEFAULT_SOURCE = Path("data/processed/fmzk_test.gpkg")
DEFAULT_OUTPUT = Path("data/processed/kataster")
DEFAULT_CACHE = Path("data/cache/kataster")
ZOOM = 16
WEBMERCATOR_RADIUS = 20037508.342789244
STRASSEN_CODES = frozenset((95, 65))
# Auch 42 (Parkplätze) und 92 (Schienenverkehr) sind Verkehrsnutzungen,
# aber nicht automatisch ein Teil des öffentlichen Straßenraums.
TRAFFIC_CONTEXT_CODES = frozenset((42, 92))
KNOWN_NAMES = {
	40: "Dauerkulturanlagen oder Erwerbsgärten",
	41: "Gebäude", 42: "Parkplätze",
	48: "Äcker, Wiesen oder Weiden", 52: "Gärten",
	53: "Weingärten", 54: "Alpen", 55: "Krummholzflächen",
	56: "Wälder", 57: "Verbuschte Flächen", 58: "Forststraßen",
	59: "Fließende Gewässer", 60: "Stehende Gewässer",
	61: "Feuchtgebiete", 62: "Vegetationsarme Flächen",
	63: "Betriebsflächen", 64: "Gewässerrandflächen",
	65: "Verkehrsrandflächen", 72: "Friedhöfe",
	83: "Gebäudenebenflächen", 84: "Abbauflächen, Halden und Deponien",
	87: "Fels- und Geröllflächen", 88: "Gletscher",
	92: "Schienenverkehrsanlagen", 95: "Straßenverkehrsanlagen",
	96: "Freizeitflächen",
}
NAME_CODES = {value.casefold(): key for key, value in KNOWN_NAMES.items()}
TABLE_FIELDS = (
	"kgez", "gnr", "klasse", "grund", "rechtstatus", "fmzk_kern_ueberlappung_m2",
	"kataster_tile_flaeche_im_ausschnitt_m2", "nutzungscodes",
	"strassen_nutzung_m2", "sonstige_nutzung_m2", "beobachtete_nfl_codes",
	"tile_nutzungshinweis", "api_url", "details_status",
)


def tile_index(lon, lat, zoom=ZOOM):
	lat = max(-85.05112878, min(85.05112878, lat))
	n = 2 ** zoom
	x = math.floor((lon + 180) / 360 * n)
	y = math.floor((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
	return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def tiles_for_bbox(bbox, zoom=ZOOM, margin=1):
	west, south, east, north = bbox
	left, top = tile_index(west, north, zoom)
	right, bottom = tile_index(east, south, zoom)
	n = 2 ** zoom
	return [(zoom, x, y)
		for x in range(max(0, left - margin), min(n - 1, right + margin) + 1)
		for y in range(max(0, top - margin), min(n - 1, bottom + margin) + 1)]


def fetch_bytes(url, *, timeout=25):
	request = Request(url, headers={"User-Agent": "ks-Gartenstrassen/kataster-validation (BEV public data)"})
	with urlopen(request, timeout=timeout) as response:
		data = response.read(12_000_001)
	if len(data) > 12_000_000:
		raise ValueError(f"BEV-Antwort zu groß: {url}")
	return data


def cached_request(url, path, *, refresh=False, offline=False):
	if path.is_file() and not refresh:
		return path.read_bytes()
	if offline:
		raise FileNotFoundError(f"Offline-Cache fehlt: {path}")
	data = fetch_bytes(url)
	if not data:
		raise ValueError(f"Leere BEV-Antwort: {url}")
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp = path.with_suffix(path.suffix + ".tmp")
	tmp.write_bytes(data)
	tmp.replace(path)
	return data


def decode_tile(raw, z, x, y):
	"""Tile-Koordinaten mit Ursprung oben links -> metrisch EPSG:31256."""
	if raw.startswith(b"\x1f\x8b"):
		raw = gzip.decompress(raw)
	layers = mapbox_vector_tile.decode(raw, default_options={"y_coord_down": True})
	to_local = Transformer.from_crs("EPSG:3857", "EPSG:31256", always_xy=True).transform
	width = 2 * WEBMERCATOR_RADIUS / (2 ** z)
	minx = -WEBMERCATOR_RADIUS + x * width
	maxy = WEBMERCATOR_RADIUS - y * width
	features = {"gst": [], "nfl": []}
	for layer_name in features:
		# Leere Quelllayer können in einzelnen MVT-Kacheln fehlen.
		# Erst nach dem Zusammenführen wird geprüft, ob im gesamten
		# Testbereich sowohl gst als auch nfl vorhanden sind.
		layer = layers.get(layer_name)
		if layer is None:
			continue
		extent = layer.get("extent", 4096)
		if not isinstance(extent, int) or extent <= 0:
			raise ValueError(f"Kachel {z}/{x}/{y}: ungültiger Kachelextent")
		factor = width / extent
		def from_tile(tx, ty, tz=None):
			return minx + tx * factor, maxy - ty * factor
		for feature in layer.get("features", []):
			if feature.get("geometry") is None:
				continue
			geom_3857 = transform(from_tile, shape(feature["geometry"]))
			if geom_3857.is_empty or geom_3857.geom_type not in ("Polygon", "MultiPolygon"):
				continue
			geom = transform(to_local, geom_3857)
			if not geom.is_valid:
				geom = geom.buffer(0)
			if geom.is_empty or geom.area <= 0:
				continue
			features[layer_name].append((feature.get("properties") or {}, geom))
	return features


def cadastral_key(properties):
	kgez = str(properties.get("kgez") or properties.get("kg") or "").strip()
	gnr = str(properties.get("gnr") or "").strip()
	if kgez.isdigit():
		kgez = kgez.zfill(5)
	return (kgez, gnr) if kgez and gnr else None


def read_tiles(bbox, cache, *, refresh=False, offline=False, max_tiles=36):
	tiles = tiles_for_bbox(bbox)
	if len(tiles) > max_tiles:
		raise ValueError(f"Erwartet {len(tiles)} Kacheln, maximal {max_tiles}; BBOX prüfen")
	gst = defaultdict(list)
	nfl = []
	missing_ids = 0
	for z, x, y in tiles:
		url = f"{BASE}/tiles/kataster/{z}/{x}/{y}.pbf"
		raw = cached_request(url, cache / "tiles" / str(z) / str(x) / f"{y}.pbf",
			refresh=refresh, offline=offline)
		result = decode_tile(raw, z, x, y)
		for properties, geometry in result["gst"]:
			key = cadastral_key(properties)
			if key is None:
				missing_ids += 1
				continue
			gst[key].append(geometry)
		nfl.extend(result["nfl"])
	if missing_ids:
		raise ValueError(f"{missing_ids} Grundstücksfragmente ohne kgez/gnr; Zuordnung nicht vollständig")
	if not gst:
		raise ValueError("Keine Grundstücke in den Katasterkacheln")
	if not nfl:
		raise ValueError("Keine Nutzungsflächen in den Katasterkacheln")
	return {key: union_all(parts) for key, parts in gst.items()}, nfl, tiles


def detail_url(kgez, gnr):
	return f"{BASE}/api/gst/{quote(kgez, safe='')}/{quote(gnr, safe='/')}/"


def usage_code(item, key=None):
	"""Nur eindeutig belegbare Codes bzw. exakt bekannte BEV-Bezeichnungen."""
	for attr in ("ns", "nu", "code"):
		value = item.get(attr)
		if value is not None and str(value).isdigit() and int(value) in KNOWN_NAMES:
			return int(value)
	value = item.get("nutzung")
	if value is not None:
		if str(value).isdigit() and int(value) in KNOWN_NAMES:
			return int(value)
		clean = " ".join(str(value).casefold().split())
		if clean in NAME_CODES:
			return NAME_CODES[clean]
	if key is not None and str(key).isdigit() and int(key) in KNOWN_NAMES:
		return int(key)
	return None


def parse_whole_parcel(detail):
	parcel = detail.get("properties") or detail.get("parcel", {}).get("properties") or {}
	if not isinstance(parcel, dict):
		raise ValueError("BEV-Grundstück: properties fehlen")
	raw = parcel.get("nutzungen")
	if not isinstance(raw, (dict, list)) or not raw:
		raise ValueError("BEV-Grundstück: vollständige Nutzungsbilanz fehlt")
	entries = list(raw.items()) if isinstance(raw, dict) else list(enumerate(raw))
	by_code = defaultdict(float)
	unknown = []
	for key, item in entries:
		if not isinstance(item, dict):
			unknown.append({"key": str(key), "grund": "unbekanntes Format"})
			continue
		code = usage_code(item, key)
		area = item.get("fl")
		try:
			amount = float(area)
		except (ValueError, TypeError):
			unknown.append({"key": str(key), "nutzung": item.get("nutzung"), "grund": "Fläche fehlt"})
			continue
		if not math.isfinite(amount) or amount < 0:
			unknown.append({"key": str(key), "nutzung": item.get("nutzung"), "grund": "ungültige Fläche"})
			continue
		if code is None:
			unknown.append({"key": str(key), "nutzung": item.get("nutzung"), "flaeche": amount})
			continue
		by_code[code] += amount
	return dict(sorted(by_code.items())), unknown, parcel


def classify_usages(usages, unknown):
	if unknown or not usages or any(value <= 0 for value in usages.values()):
		return "D", "Unvollständige oder unbekannte Nutzungsangaben"
	codes = set(usages)
	if codes <= STRASSEN_CODES:
		return "A", "Nur Straßenverkehrsanlagen/Verkehrsrandflächen (95/65)"
	if codes & STRASSEN_CODES:
		return "B", "Straßennutzung und weitere Nutzungen auf demselben Grundstück"
	if codes & TRAFFIC_CONTEXT_CODES:
		return "C", "Keine 95/65; andere Verkehrsnutzungen, daher gesondert prüfen"
	return "C", "FMZK-Kern liegt auf einem Grundstück ohne Straßen-/Verkehrsrandnutzung"


def build_results(core, parcels, nfl, clip, details):
	"""Stichprobe in der BBOX; Einordnung A/B/C nur anhand kompletter API-Nutzungen."""
	results = []
	parcel_geometries = []
	nfl_geometries = []
	clip_core = core.intersection(clip)
	for (kgez, gnr), geometry in sorted(parcels.items()):
		clipped = geometry.intersection(clip)
		if clipped.is_empty or clipped.area <= 0:
			continue
		intersection = clipped.intersection(clip_core).area
		if intersection <= 0:
			continue
		key = (kgez, gnr)
		detail = details.get(key)
		if not detail or detail.get("error"):
			usages, unknown, properties = {}, [], {}
			class_name, reason = "D", "Detailabfrage fehlt oder ist fehlgeschlagen"
			detail_status = str((detail or {}).get("error") or "fehlt")
		else:
			try:
				usages, unknown, properties = parse_whole_parcel(detail)
				class_name, reason = classify_usages(usages, unknown)
				detail_status = "ok" if class_name != "D" else "nutzungen_unvollstaendig"
			except (ValueError, AttributeError, TypeError) as exc:
				usages, unknown, properties = {}, [], {}
				class_name, reason = "D", str(exc)
				detail_status = "ungültige_Antwort"
		seen_codes = set()
		for p, part in nfl:
			if not part.intersects(clipped):
				continue
			overlap = part.intersection(clipped)
			if overlap.area <= 0.05:
				continue
			code = p.get("ns")
			if code is not None:
				seen_codes.add(str(code))
		# Tile-Code-Hinweise beziehen sich NUR auf den untersuchten
		# Ausschnitt und sind kein Ersatz für die Grundstücks-API.
		observed = {int(value) for value in seen_codes if str(value).isdigit()}
		if not seen_codes or len(observed) != len(seen_codes):
			tile_hint = "unvollstaendig_oder_unbekannt"
		elif observed <= STRASSEN_CODES:
			tile_hint = "nur_95_65_im_ausschnitt"
		elif observed & STRASSEN_CODES:
			tile_hint = "gemischt_im_ausschnitt"
		else:
			tile_hint = "keine_95_65_im_ausschnitt"
		row = {
			"kgez": kgez, "gnr": gnr, "klasse": class_name,
			"grund": reason, "rechtstatus": properties.get("rstatus") or "",
			"fmzk_kern_ueberlappung_m2": round(intersection, 2),
			"kataster_tile_flaeche_im_ausschnitt_m2": round(clipped.area, 2),
			"nutzungscodes": ",".join(map(str, sorted(usages))),
			"strassen_nutzung_m2": sum(area for code, area in usages.items() if code in STRASSEN_CODES),
			"sonstige_nutzung_m2": sum(area for code, area in usages.items() if code not in STRASSEN_CODES),
			"beobachtete_nfl_codes": ",".join(sorted(seen_codes)),
			"tile_nutzungshinweis": tile_hint,
			"api_url": detail_url(kgez, gnr),
			"details_status": detail_status,
		}
		results.append({"table": row, "usages": usages, "unknown": unknown})
		parcel_geometries.append({"type": "Feature", "properties": row,
			"geometry": mapping(clipped)})
		# Nur die Nutzungsflächen innerhalb des ausgewählten Grundstücksteils
		# und der BBOX zeigen, ohne sie als vollständig auszugeben.
		for p, part in nfl:
			if not part.intersects(clipped):
				continue
			fragment = part.intersection(clipped)
			if fragment.area <= 0.05:
				continue
			nfl_geometries.append({"type": "Feature", "properties": {
				"kgez": kgez, "gnr": gnr, "ns": p.get("ns"),
				"vollstaendig": False,
			}, "geometry": mapping(fragment)})
	return results, parcel_geometries, nfl_geometries


def write_results(output, results, parcels_geojson, nfl_geojson, tiles, bbox, failures):
	from csv import DictWriter
	from pyproj import Transformer
	output.mkdir(parents=True, exist_ok=True)
	to_wgs84 = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform
	def geojson(features):
		return {
			"type": "FeatureCollection",
			"features": [
				{**feature, "geometry": mapping(transform(to_wgs84, shape(feature["geometry"])))}
				for feature in features
			],
		}
	(output / "kataster_grundstuecke.geojson").write_text(
		json.dumps(geojson(parcels_geojson), ensure_ascii=False) + "\n", encoding="utf-8")
	(output / "kataster_nfl_ausschnitt.geojson").write_text(
		json.dumps(geojson(nfl_geojson), ensure_ascii=False) + "\n", encoding="utf-8")
	with (output / "kataster_grundstuecke.csv").open("w", newline="", encoding="utf-8-sig") as file:
		writer = DictWriter(file, fieldnames=TABLE_FIELDS)
		writer.writeheader()
		writer.writerows(item["table"] for item in results)
	tally = Counter(item["table"]["klasse"] for item in results)
	report = {
		"hinweis": "A/B/C beschreiben Kataster-Nutzungsarten, keine öffentliche Widmung. D bedeutet unvollständige Daten.",
		"stand_auswertung": datetime.now(timezone.utc).isoformat(),
		"bbox_lon_lat": list(bbox),
		"zoom": ZOOM,
		"tiles_abgerufen": [list(tile) for tile in tiles],
		"grundstuecke": len(results),
		"klassen": dict(sorted(tally.items())),
		"api_fehler": failures,
		"nfl_geojson_nur_testausschnitt": True,
		"grundstueck_geojson_nur_tileausschnitt": True,
		"vollstaendige_nutzungsbilanz_aus_api": bool(results) and all(
			item["table"]["details_status"] == "ok" for item in results
		),
		"grundstuecke_mit_api_nutzungsbilanz": sum(
			item["table"]["details_status"] == "ok" for item in results
		),
		"details": [{"kgez": item["table"]["kgez"], "gnr": item["table"]["gnr"],
			"klasse": item["table"]["klasse"], "nutzungen_m2": item["usages"],
			"nicht_zugeordnet": item["unknown"]} for item in results],
	}
	(output / "kataster_bericht.json").write_text(
		json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	return report


def load_parcel_details(keys, cache, *, online=False, refresh=False, pause=0.15):
	"""Cache immer verwenden; online nur nach explizitem Opt-in.

	Ein 429/5xx-Status oder Netzwerkfehler öffnet den Schutzschalter:
	Keine weiteren Anfragen bei derselben Störung. Bereits vorhandene
	Detailantworten bleiben nutzbar, andere Grundstücke bleiben Klasse D.
	"""
	details = {}
	failures = []
	disabled_reason = ""
	requests_made = 0
	for kgez, gnr in keys:
		key = (kgez, gnr)
		path = cache / "details" / kgez / (quote(gnr, safe="") + ".json")
		if path.is_file() and not refresh:
			try:
				details[key] = json.loads(path.read_text(encoding="utf-8"))
			except (OSError, ValueError, UnicodeError) as exc:
				details[key] = {"error": "Cache ungültig: " + str(exc)}
			continue
		if not online or disabled_reason:
			details[key] = {"error": disabled_reason or "keine API-Daten im Cache"}
			continue
		if requests_made and pause > 0:
			time.sleep(pause)
		requests_made += 1
		try:
			url = detail_url(kgez, gnr)
			raw = cached_request(url, path, refresh=refresh)
			details[key] = json.loads(raw.decode("utf-8"))
		except (HTTPError, URLError, OSError, ValueError, UnicodeError) as exc:
			details[key] = {"error": str(exc)}
			failures.append({"kgez": kgez, "gnr": gnr, "fehler": str(exc)})
			if (isinstance(exc, HTTPError) and (exc.code == 429 or exc.code >= 500)
				or isinstance(exc, (URLError, TimeoutError, ConnectionError))):
				disabled_reason = "API-Störung nach " + str(requests_made) + " Anfrage(n): " + str(exc)
	return details, failures, disabled_reason


def run(source=DEFAULT_SOURCE, output=DEFAULT_OUTPUT, cache=DEFAULT_CACHE,
	*, online_details=False, offline=False, refresh=False, pause=0.15,
	max_tiles=36, max_parcels=250):
	if offline and refresh:
		raise ValueError("--offline und --refresh schließen sich aus")
	if offline and online_details:
		raise ValueError("--offline und --details schließen sich aus")
	if refresh and not online_details:
		raise ValueError("--refresh setzt --details voraus")
	features, manifest, clip, _ = load_polygons(source)
	core_shapes = [geom for _, code, _, geom in features if code in CORE_CODES]
	if not core_shapes:
		raise ValueError("Keine FMZK-Kernflächen vorhanden")
	core = union_all(core_shapes)
	bbox = manifest["bbox_lon_lat"]
	parcels, nfl, tiles = read_tiles(bbox, Path(cache), refresh=refresh,
		offline=offline, max_tiles=max_tiles)
	keys = [key for key, geometry in sorted(parcels.items())
		if geometry.intersection(core).area > 0
		and geometry.intersection(clip).area > 0]
	if len(keys) > max_parcels:
		raise ValueError(f"{len(keys)} getroffene Grundstücke, maximal {max_parcels}; bitte kleineres Gebiet")
	details, failures, disabled_reason = load_parcel_details(
		keys, Path(cache), online=online_details, refresh=refresh,
		pause=pause
	)
	results, polygons, uses = build_results(core, parcels, nfl, clip, details)
	report = write_results(Path(output), results, polygons, uses, tiles, bbox, failures)
	report["detail_abfragen_online"] = online_details
	report["detail_abbruchgrund"] = disabled_reason
	(Path(output) / "kataster_bericht.json").write_text(
		json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
	)
	print(f"Kataster z{ZOOM}: {len(tiles)} Kacheln, {len(parcels)} Grundstücks-IDs in Tiles")
	print(f"FMZK-Kern trifft {report['grundstuecke']} Grundstücke")
	for category in ("A", "B", "C", "D"):
		print(f"  {category}: {report['klassen'].get(category, 0)}")
	if disabled_reason:
		print(f"Detail-API: {disabled_reason}")
	if not online_details:
		print("Keine neuen Grundstücks-API-Abfragen (Standardmodus; Cache wird genutzt).")
	if failures:
		print(f"Warnung: {len(failures)} Detailabfragen fehlgeschlagen; diese Grundstücke bleiben D")
	print(f"Ausgabe: {Path(output).resolve()}")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
	parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
	parser.add_argument("--offline", action="store_true", help="Ausschließlich bereits geladene Daten verwenden")
	parser.add_argument("--refresh", action="store_true", help="BEV-Daten neu laden; nur zusammen mit --details")
	parser.add_argument("--details", action="store_true", help="Vollständige Grundstücksdetails online abrufen; stoppt bei API-Störung")
	parser.add_argument("--max-tiles", type=int, default=36)
	parser.add_argument("--max-parcels", type=int, default=250)
	args = parser.parse_args()
	try:
		run(args.source, args.out_dir, args.cache_dir, online_details=args.details,
			offline=args.offline, refresh=args.refresh,
			max_tiles=args.max_tiles, max_parcels=args.max_parcels)
	except (OSError, ValueError, KeyError, TypeError, URLError, HTTPError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
