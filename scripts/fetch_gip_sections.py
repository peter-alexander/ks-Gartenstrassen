#!/usr/bin/env python3
"""Modul 5 / Stufe 1: kleine Wiener GIP-Straßenachsen und Knoten abrufen.

Speichert beide WFS-Antworten roh und erzeugt getrennte GeoJSON-Prüflayer
für Kartensammlung/QGIS. Keine Straßenraumaufteilung, kein Flächenranking.
Kein Wien-Gesamtdownload; ein bereits fertiger Lauf bleibt unverändert.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pyproj import Transformer
from shapely.geometry import box, mapping, shape
from shapely.ops import transform

from scripts.fmzk_source import load_polygons
from scripts.geojson_crs import require_geojson_lonlat

SERVICE = "https://data.wien.gv.at/daten/geo"
DATASET = "https://www.data.gv.at/datasets/1039ed7e-97fb-435f-b6cc-f6a105ba5e09"
LAYERS = {
	"achsen": "ogdwien:STRASSENGRAPHOGD",
	"knoten": "ogdwien:STRASSENKNOTENOGD",
}
RAW_NAMES = {
	"achsen": "gip_strassengraph_wfs.geojson",
	"knoten": "gip_strassenknoten_wfs.geojson",
}
VIEW_NAMES = {
	"achsen": "abschnitte_achsen.geojson",
	"knoten": "abschnitte_knoten.geojson",
}
REPORT_NAME = "gip_probe_bericht.json"
DEFAULT_FMZK = Path("data/processed/fmzk_test.gpkg")
DEFAULT_OUTPUT = Path("data/processed/strassenabschnitte/gip")
DEFAULT_PADDING_M = 75
DEFAULT_MAX_FEATURES = 4000
MAX_RESPONSE_BYTES = 30_000_000
TO_3857 = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform


def request_bbox(area, *, padding_m=DEFAULT_PADDING_M):
	"""BBOX in Web Mercator; Puffer ist in lokalen metrischen Koordinaten."""
	if not math.isfinite(padding_m) or not 25 <= padding_m <= 200:
		raise ValueError("GIP-Randbereich muss zwischen 25 und 200 m liegen")
	if area.is_empty or not area.is_valid:
		raise ValueError("Ungültige FMZK-Testgeometrie")
	return transform(
		Transformer.from_crs("EPSG:31256", "EPSG:3857",
			always_xy=True).transform,
		area.buffer(padding_m).segmentize(5),
	).bounds


def build_wfs_url(layer, bbox, *, max_features=DEFAULT_MAX_FEATURES):
	"""WFS 1.1.0: BBOX explizit 3857, GeoJSON-Ausgabe explizit 4326."""
	if layer not in LAYERS.values():
		raise ValueError(f"Unbekannter GIP-WFS-Layer: {layer}")
	if not 100 <= max_features <= 10000:
		raise ValueError("maxFeatures muss zwischen 100 und 10000 liegen")
	if len(bbox) != 4 or any(not math.isfinite(x) for x in bbox):
		raise ValueError("Ungültige GIP-Anfrage-BBOX")
	x0, y0, x1, y1 = bbox
	if not (x0 < x1 and y0 < y1 and x1-x0 <= 5000 and y1-y0 <= 5000):
		raise ValueError("GIP-Anfrage ist für eine Testregion zu groß")
	return SERVICE + "?" + urlencode([
		("service", "WFS"), ("request", "GetFeature"), ("version", "1.1.0"),
		("typeName", layer), ("outputFormat", "json"),
		("srsName", "EPSG:4326"),
		("bbox", ",".join(map(str, bbox)) + ",EPSG:3857"),
		("maxFeatures", max_features),
	])


def _require_identifier(properties, label):
	identifier = properties.get("GIP_OBJECTID")
	if not isinstance(identifier, (int, str)) or isinstance(identifier, bool):
		raise ValueError(f"{label}: GIP_OBJECTID fehlt oder ist ungültig")
	identifier = str(identifier).strip()
	if not identifier:
		raise ValueError(f"{label}: GIP_OBJECTID ist leer")
	return identifier


def _count_reported_features(data, count):
	"""WFS-Caps erkennen, auch bei erklärter Gesamtmenge im JSON."""
	for key in ("totalFeatures", "numberMatched"):
		value = data.get(key)
		if value is None or value == "unknown":
			continue
		try:
			total = int(value)
		except (TypeError, ValueError, OverflowError):
			raise ValueError(f"WFS enthält ungültiges {key}: {value!r}")
		if total > count:
			raise ValueError(
				f"WFS meldet {total} Features, lieferte aber nur {count}; "
				"unvollständige Antwort")
		if total < count:
			raise ValueError(f"WFS enthält widersprüchliches {key}: {total} < {count}")


def validate_layer(raw, kind, bbox, *, max_features=DEFAULT_MAX_FEATURES,
	allow_bbox_envelope_match=False):
	"""Original-GeoJSON fachlich/technisch prüfen und Karten-Layer erstellen.

	WFS-Geometrien dürfen die BBOX überschreiten. GeoServer kann bei
	BBOX-Anfragen auch Features zurückliefern, deren *Hüllrechteck* die
	Anfrage schneidet, aber deren tatsächliche gekrümmte Liniengeometrie
	die Anfrage nicht berührt (räumlicher Index / BBOX-Vorfilter).
	Im kleinen Diagnose-Ausschnitt gilt weiterhin der strenge
	Geometrieschnitt. Die Wienweite Pipeline darf Hüllrechteck-Treffer
	mit expliziter Diagnose annehmen – niemals beliebig entfernte
	Objekte verwerfen oder automatisch akzeptieren.
	GIP_OBJECTID-Duplikate werden *dokumentiert*, nicht zusammengelegt.
	"""
	if kind not in LAYERS:
		raise ValueError(f"Unbekannter GIP-Datentyp {kind!r}")
	if len(raw) > MAX_RESPONSE_BYTES:
		raise ValueError(f"{kind}: WFS-Antwort überschreitet 30 MB")
	try:
		data = json.loads(raw.decode("utf-8-sig"))
	except (UnicodeError, json.JSONDecodeError) as exc:
		raise ValueError(f"{kind}: WFS lieferte kein gültiges GeoJSON") from exc
	if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
		raise ValueError(f"{kind}: WFS lieferte keine GeoJSON-FeatureCollection")
	require_geojson_lonlat(data, label=f"GIP {kind}")
	features = data.get("features")
	if not isinstance(features, list) or not features:
		raise ValueError(f"{kind}: keine GIP-Features für die Test-BBOX")
	if len(features) >= max_features:
		raise ValueError(
			f"{kind}: WFS-Limit {max_features} erreicht; Teilantwort abgewiesen")
	_count_reported_features(data, len(features))
	query_area = box(*bbox)
	ids = Counter()
	source_ids = Counter()
	names = Counter()
	formats = Counter()
	envelope_only_ids = []
	view_features = []
	for index, feature in enumerate(features):
		label = f"{kind} Feature {index}"
		if not isinstance(feature, dict) or feature.get("type") != "Feature":
			raise ValueError(f"{label}: ungültiges GeoJSON-Feature")
		properties = feature.get("properties")
		if not isinstance(properties, dict):
			raise ValueError(f"{label}: Properties fehlen")
		identifier = _require_identifier(properties, label)
		ids[identifier] += 1
		source_id = feature.get("id")
		if source_id is not None:
			if not isinstance(source_id, (int, str)) or isinstance(source_id, bool):
				raise ValueError(f"{label}: ungültige WFS-Feature-ID")
			source_ids[str(source_id)] += 1
		try:
			geometry = shape(feature["geometry"])
		except (KeyError, TypeError, ValueError, AttributeError) as exc:
			raise ValueError(f"{label}: Geometrie nicht lesbar") from exc
		valid_types = ("LineString", "MultiLineString") if kind == "achsen" else ("Point",)
		if geometry.geom_type not in valid_types or geometry.is_empty:
			raise ValueError(f"{label}: {geometry.geom_type} statt {valid_types}")
		if not geometry.is_valid or (kind == "achsen" and geometry.length <= 0):
			raise ValueError(f"{label}: ungültige oder flächenlose/linienlose Geometrie")
		if any(not math.isfinite(v) for v in geometry.bounds):
			raise ValueError(f"{label}: nicht-endliche Koordinaten")
		lon0, lat0, lon1, lat1 = geometry.bounds
		if not (15.8 <= lon0 <= lon1 <= 17.1
			and 47.8 <= lat0 <= lat1 <= 48.6):
			raise ValueError(f"{label}: GeoJSON-Koordinaten nicht plausibel für Wien")
		mercator_geometry = transform(TO_3857, geometry)
		envelope_only = False
		if not mercator_geometry.intersects(query_area):
			# Eine WFS-BBOX ist ein Bounding-Box-Filter und keine
			# zwingend exakte GEOS-intersects-Abfrage. Die Hülle
			# kann die Kachel überdecken, obwohl die Linie sie
			# umrundet. Nur diesen nachvollziehbaren Fall zulassen.
			envelope_only = box(*mercator_geometry.bounds).intersects(query_area)
			if not (allow_bbox_envelope_match and envelope_only and kind == "achsen"):
				raise ValueError(
					f"{label}, GIP_OBJECTID={identifier}: Feature liegt "
					f"außerhalb der WFS-BBOX (Abstand "
					f"{mercator_geometry.distance(query_area):.3f} m, "
					f"Hüllrechteck-Treffer={envelope_only})")
			envelope_only_ids.append(identifier)
		name = properties.get("FEATURENAME") or properties.get("REG_STRNAME") or ""
		if not isinstance(name, str):
			name = str(name)
		names[name or "(ohne Namen)"] += 1
		formats[geometry.geom_type] += 1
		view_features.append({
			"type": "Feature",
			"id": source_id if source_id is not None else f"gip:{identifier}:{index}",
			"geometry": mapping(geometry),
			"properties": {
				"gip_objectid": identifier,
				"wfs_id": str(source_id) if source_id is not None else None,
				"name": name,
				"feature_name": properties.get("FEATURENAME"),
				"reg_strname": properties.get("REG_STRNAME"),
				"node_from": properties.get("NODEFROM_OBJECTID"),
				"node_to": properties.get("NODETO_OBJECTID"),
				"fow": properties.get("FOW"),
				"frc": properties.get("FRC"),
				"edgecategory": properties.get("EDGECATEGORY"),
				"dedicatedwidth": properties.get("DEDICATEDWIDTH"),
				"wfs_bbox_nur_huelle": envelope_only,
				"status": "nur_quellgeometrie_ungepruefte_abschnittsflaeche",
			},
		})
	duplicate_ids = {key: number for key, number in ids.items() if number > 1}
	duplicate_source_ids = {key: number for key, number in source_ids.items() if number > 1}
	summary = {
		"anzahl": len(features),
		"geometrietypen": dict(formats),
		"verschiedene_gip_ids": len(ids),
		"doppelte_gip_ids": duplicate_ids,
		"doppelte_wfs_feature_ids": duplicate_source_ids,
		"wfs_bbox_nur_huelle_anzahl": len(envelope_only_ids),
		"wfs_bbox_nur_huelle_gip_ids": envelope_only_ids,
		"namen_top_15": names.most_common(15),
		"quelle_sha256": hashlib.sha256(raw).hexdigest(),
	}
	return data, {"type": "FeatureCollection", "features": view_features}, summary


def _download(url):
	request = Request(url, headers={
		"User-Agent": "ks-Gartenstrassen/1.0 (lokale GIP-Stichprobe)",
		"Accept": "application/json",
	})
	with urlopen(request, timeout=45) as response:
		raw = response.read(MAX_RESPONSE_BYTES + 1)
	if len(raw) > MAX_RESPONSE_BYTES:
		raise ValueError("WFS-Antwort überschreitet die 30-MB-Sicherheitsgrenze")
	return raw


def _write_json(path, document):
	path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
		encoding="utf-8")


def run(fmzk=DEFAULT_FMZK, output=DEFAULT_OUTPUT, *,
	padding_m=DEFAULT_PADDING_M, max_features=DEFAULT_MAX_FEATURES,
	offline=False, refresh=False, downloader=None):
	"""Erzeugt Raw-Layer + Kartenprobe erst nach Validierung beider WFS-Sätze."""
	if offline and refresh:
		raise ValueError("--offline und --refresh schließen sich aus")
	_, manifest, clip, _ = load_polygons(fmzk)
	bbox = request_bbox(clip, padding_m=padding_m)
	urls = {kind: build_wfs_url(layer, bbox, max_features=max_features)
		for kind, layer in LAYERS.items()}
	output = Path(output)
	report_path = output / REPORT_NAME
	expected_files = [report_path] + [
		output / name for name in (*RAW_NAMES.values(), *VIEW_NAMES.values())
	]
	exists = [path.exists() for path in expected_files]
	if any(exists) and not all(exists) and not refresh:
		raise ValueError("Unvollständiger GIP-Datensatz; anderes --out-dir "
			"oder explizit --refresh verwenden")
	cache = all(exists) and not refresh
	if offline and not cache:
		raise FileNotFoundError("Vollständiger lokaler GIP-Cache fehlt")
	if cache:
		old_report = json.loads(report_path.read_text(encoding="utf-8"))
		if old_report.get("anfragen") != urls:
			raise ValueError("GIP-Cache gehört zu anderem FMZK-Ausschnitt, "
				"anderen WFS-Parametern oder anderem maxFeatures")
		if old_report.get("fmzk_bbox_lon_lat") != manifest["bbox_lon_lat"]:
			raise ValueError("GIP-Cache passt nicht zur aktuellen FMZK-BBOX")
		if old_report.get("randbereich_m") != padding_m:
			raise ValueError("GIP-Cache passt nicht zum aktuellen Randbereich")
		raws = {kind: (output / RAW_NAMES[kind]).read_bytes() for kind in LAYERS}
	else:
		fetch = downloader or _download
		# Noch *nichts* schreiben: auch ein Fehlschlag bei Knoten darf
		# keinen irreführend vollständigen Achsen-Datensatz hinterlassen.
		raws = {kind: fetch(url) for kind, url in urls.items()}
	views = {}
	summaries = {}
	for kind, raw in raws.items():
		_, view, summary = validate_layer(raw, kind, bbox,
			max_features=max_features)
		views[kind] = view
		summaries[kind] = summary
	if cache:
		for kind, details in summaries.items():
			stored = old_report.get("datensaetze", {}).get(kind, {})
			if stored.get("quelle_sha256") != details["quelle_sha256"]:
				raise ValueError(f"{kind}: Cache-SHA-256 stimmt nicht")
		print("GIP-Probe: geprüfter lokaler Cache unverändert")
		return old_report
	report = {
		"schema_version": 1,
		"created_utc": datetime.now(timezone.utc).isoformat(),
		"status": "GIP-QUELLPROBE – KEINE STRASSENABSCHNITTS-FLAECHEN",
		"datensatz": DATASET,
		"lizenz": "CC BY 4.0 – Stadt Wien",
		"fmzk": str(fmzk),
		"fmzk_bbox_lon_lat": manifest["bbox_lon_lat"],
		"bbox_3857_mit_rand": list(bbox),
		"randbereich_m": padding_m,
		"max_features_pro_layer": max_features,
		"anfragen": urls,
		"datensaetze": summaries,
		"dateien": {"originale": RAW_NAMES, "kartenlayer": VIEW_NAMES},
		"hinweis": (
			"Abschnittsachsen und Kreuzungsknoten sind lediglich "
			"Quellgeometrien; noch keine exklusive Flächenzuordnung. "
			"GIP_OBJECTID-Duplikate werden nicht zusammengeführt."
		),
	}
	output.mkdir(parents=True, exist_ok=True)
	# Einzelne Dateien atomar ersetzen, Abschlussmarke ist der Bericht.
	# Ein unterbrochener Lauf ist am fehlenden/alten Bericht erkennbar.
	for kind, raw in raws.items():
		dest = output / RAW_NAMES[kind]
		temp = dest.with_name(dest.name + ".tmp")
		temp.write_bytes(raw)
		temp.replace(dest)
		dest = output / VIEW_NAMES[kind]
		temp = dest.with_name(dest.name + ".tmp")
		_write_json(temp, views[kind])
		temp.replace(dest)
	temp = report_path.with_name(report_path.name + ".tmp")
	_write_json(temp, report)
	temp.replace(report_path)
	for kind, details in summaries.items():
		print(f"GIP {kind}: {details['anzahl']} Features, "
			f"{len(details['doppelte_gip_ids'])} mehrfach vorkommende GIP-IDs")
	print(f"Prüf-Layer und Bericht: {output}")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--fmzk", type=Path, default=DEFAULT_FMZK)
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
	parser.add_argument("--padding-m", type=float, default=DEFAULT_PADDING_M)
	parser.add_argument("--max-features", type=int, default=DEFAULT_MAX_FEATURES)
	parser.add_argument("--offline", action="store_true")
	parser.add_argument("--refresh", action="store_true")
	args = parser.parse_args()
	try:
		run(args.fmzk, args.out_dir, padding_m=args.padding_m,
			max_features=args.max_features, offline=args.offline,
			refresh=args.refresh)
	except (OSError, ValueError, TypeError, KeyError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
