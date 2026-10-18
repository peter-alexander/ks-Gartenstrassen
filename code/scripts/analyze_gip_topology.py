#!/usr/bin/env python3
"""Modul 5 / Stufe 2: Topologie-Audit der lokal geprüften GIP-Achsen/Knoten.

Nur Diagnose, keinerlei Flächen- oder Segmentzuweisung. Prüft echte
NODEFROM_OBJECTID/NODETO_OBJECTID-Verknüpfungen, metrische Endpunkte,
Randknoten, isolierte Teilnetze und die BBOX-Überdeckung.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Point, box, shape
from shapely.ops import transform

DEFAULT_DIR = Path("data/processed/strassenabschnitte/gip")
DEFAULT_REPORT_NAME = "gip_topologie_bericht.json"
TO_METRIC = Transformer.from_crs(
	"EPSG:4326", "EPSG:31256", always_xy=True).transform
TO_MERCATOR = Transformer.from_crs(
	"EPSG:4326", "EPSG:3857", always_xy=True).transform


def read_geojson(path, *, label):
	data = json.loads(Path(path).read_text(encoding="utf-8"))
	if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
		raise ValueError(f"{label}: FeatureCollection erwartet")
	if "crs" in data:
		raise ValueError(f"{label}: Karten-GeoJSON darf kein crs-Attribut enthalten")
	features = data.get("features")
	if not isinstance(features, list) or not features:
		raise ValueError(f"{label}: leere Featureliste")
	return features


def id_value(raw, *, label):
	if not isinstance(raw, (str, int)) or isinstance(raw, bool):
		raise ValueError(f"{label}: fehlende ID")
	value = str(raw).strip()
	if not value:
		raise ValueError(f"{label}: leere ID")
	return value


def _connected_components(edges):
	adjacent = defaultdict(set)
	for start, end in edges:
		adjacent[start].add(end)
		adjacent[end].add(start)
	seen = set()
	components = []
	for first in sorted(adjacent):
		if first in seen:
			continue
		found = {first}
		stack = [first]
		seen.add(first)
		while stack:
			current = stack.pop()
			for neighbor in adjacent[current]:
				if neighbor not in seen:
					seen.add(neighbor)
					found.add(neighbor)
					stack.append(neighbor)
		components.append(found)
	return sorted(components, key=lambda c: (-len(c), sorted(c)[0]))


def audit(axes, nodes, probe, *, endpoint_tolerance_m=0.5):
	"""Expliziter Diagnosebericht, ohne Geometrien stillschweigend zu ändern."""
	if not math.isfinite(endpoint_tolerance_m) or endpoint_tolerance_m <= 0:
		raise ValueError("Endpunkt-Toleranz muss positiv und endlich sein")
	if not isinstance(probe, dict) or probe.get("schema_version") != 1:
		raise ValueError("GIP-Quellbericht v1 benötigt")
	bbox = probe.get("bbox_3857_mit_rand")
	area_bbox = probe.get("fmzk_bbox_lon_lat")
	if not isinstance(bbox, list) or len(bbox) != 4 or not all(
		isinstance(x, (int, float)) and math.isfinite(x) for x in bbox
	):
		raise ValueError("GIP-Quellbericht enthält keine gültige WFS-BBOX")
	if not isinstance(area_bbox, list) or len(area_bbox) != 4:
		raise ValueError("GIP-Quellbericht enthält keine Test-BBOX")
	query_rectangle = box(*bbox)
	original_rectangle = box(*area_bbox)
	if query_rectangle.is_empty or original_rectangle.is_empty:
		raise ValueError("GIP-Quellbericht enthält leere BBOX")

	for kind, items in (("achsen", axes), ("knoten", nodes)):
		expected = probe.get("datensaetze", {}).get(kind, {}).get("anzahl")
		if not isinstance(expected, int) or expected != len(items):
			raise ValueError(f"{kind}: Anzahl weicht vom GIP-Quellbericht ab")

	node_map = {}
	for item in nodes:
		props = item.get("properties") or {}
		node_id = id_value(props.get("gip_objectid"), label="Knoten")
		if node_id in node_map:
			raise ValueError(f"Doppelte Knoten-ID: {node_id}")
		geom = shape(item.get("geometry"))
		if geom.geom_type != "Point" or geom.is_empty or not geom.is_valid:
			raise ValueError(f"Knoten {node_id}: gültiger Point erwartet")
		node_map[node_id] = geom

	edges = []
	ref_count = Counter()
	endpoint_distances = []
	displaced = []
	missing_inside = []
	missing_outside = []
	edge_records = []
	axes_in_box = 0
	categories = Counter()
	fows = Counter()
	width_unknown = 0
	for index, item in enumerate(axes):
		props = item.get("properties") or {}
		edge_id = id_value(props.get("gip_objectid"), label=f"Achse {index}")
		start = id_value(props.get("node_from"), label=f"Achse {edge_id}: node_from")
		end = id_value(props.get("node_to"), label=f"Achse {edge_id}: node_to")
		geom = shape(item.get("geometry"))
		if geom.geom_type != "LineString" or geom.is_empty or not geom.is_valid:
			raise ValueError(f"Achse {edge_id}: gültiger LineString benötigt")
		if geom.length <= 0:
			raise ValueError(f"Achse {edge_id}: Linie ohne Länge")
		if geom.intersects(original_rectangle):
			axes_in_box += 1
		edges.append((start, end))
		categories[str(props.get("edgecategory"))] += 1
		fows[str(props.get("fow"))] += 1
		if props.get("dedicatedwidth") in (None, -1):
			width_unknown += 1
		for role, ref, coord in (
			("from", start, geom.coords[0]),
			("to", end, geom.coords[-1]),
		):
			ref_count[ref] += 1
			p = Point(coord)
			if ref in node_map:
				deviation = transform(TO_METRIC, p).distance(
					transform(TO_METRIC, node_map[ref]))
				endpoint_distances.append(deviation)
				if deviation > endpoint_tolerance_m:
					displaced.append({
						"achse": edge_id, "knoten": ref, "seite": role,
						"abweichung_m": deviation,
					})
			else:
				distance_out = transform(TO_MERCATOR, p).distance(
					query_rectangle)
				issue = {"achse": edge_id, "knoten": ref, "seite": role,
					"ausserhalb_wfs_bbox_m": distance_out}
				if distance_out <= 0.01:
					missing_inside.append(issue)
				else:
					missing_outside.append(issue)
		edge_records.append({
			"id": edge_id, "name": props.get("name") or "",
			"start": start, "end": end, "length_m":
				transform(TO_METRIC, geom).length,
		})

	components = []
	for component in _connected_components(edges):
		related = [edge for edge in edge_records
			if edge["start"] in component and edge["end"] in component]
		components.append({
			"knoten": len(component),
			"achsen": len(related),
			"laenge_m": round(sum(edge["length_m"] for edge in related), 3),
			"namen": sorted({edge["name"] for edge in related
				if edge["name"]}),
			"beispiel_gip_ids": [edge["id"] for edge in related[:10]],
		})

	in_box_nodes = sum(geom.intersects(original_rectangle)
		for geom in node_map.values())
	status = "pruefen" if missing_inside or displaced else "topologie_konsistent"
	return {
		"schema_version": 1,
		"created_utc": datetime.now(timezone.utc).isoformat(),
		"status": status,
		"hinweis": "Netzdiagnose, keine Straßenraum-Aufteilung und keine validierten Abschnittsflächen",
		"anzahl_achsen": len(axes),
		"anzahl_knoten": len(nodes),
		"achsen_im_fmzk_bbox": axes_in_box,
		"knoten_im_fmzk_bbox": in_box_nodes,
		"referenzierte_knoten_ids": len(ref_count),
		"referenzierte_knoten_vorhanden": len(set(ref_count) & node_map.keys()),
		"referenzierte_knoten_fehlen": len(set(ref_count) - node_map.keys()),
		"endpunkte_gesamt": len(axes)*2,
		"endpunkte_mit_knoten": len(endpoint_distances),
		"max_endpunktabweichung_m": max(endpoint_distances,
			default=None),
		"abweichende_endpunkte": displaced,
		"fehlende_knoten_innerhalb_wfs_bbox": missing_inside,
		"fehlende_knoten_ausserhalb_wfs_bbox": missing_outside,
		"knoten_gradverteilung": dict(sorted(
			Counter(ref_count.get(node_id, 0)
				for node_id in node_map).items())),
		"komponenten": components,
		"fow_codes": dict(fows),
		"edgecategory_codes": dict(categories),
		"dedicatedwidth_fehlt_oder_minus_eins": width_unknown,
		"offene_fachfragen": [
			"Separierte Teilnetze und FOW/EDGECATEGORY fachlich zuordnen",
			"Kreuzungsflächen ohne Doppelzählung geometrisch abgrenzen",
			"Flächenbilanz gegen die originale Straßenraum-Maske prüfen",
		],
	}


def run(directory=DEFAULT_DIR, *, output=None, tolerance_m=0.5):
	directory = Path(directory)
	report_path = directory / "gip_probe_bericht.json"
	probe = json.loads(report_path.read_text(encoding="utf-8"))
	axes = read_geojson(directory / "abschnitte_achsen.geojson", label="Achsen")
	nodes = read_geojson(directory / "abschnitte_knoten.geojson", label="Knoten")
	report = audit(axes, nodes, probe, endpoint_tolerance_m=tolerance_m)
	target = Path(output) if output is not None else directory / DEFAULT_REPORT_NAME
	if target.exists():
		raise FileExistsError(f"Bericht existiert bereits: {target}; --out verwenden")
	target.parent.mkdir(parents=True, exist_ok=True)
	target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
		encoding="utf-8")
	print(f"GIP-Topologie: {report['status']}; {report['anzahl_achsen']} Achsen, "
		f"{report['anzahl_knoten']} Knoten")
	print(f"Endpunkte: {report['endpunkte_mit_knoten']} verknüpft; "
		f"{len(report['fehlende_knoten_ausserhalb_wfs_bbox'])} "
		"außerhalb der Anfrage-BBOX")
	print(f"Zusammenhängende Teilnetze: {len(report['komponenten'])}; "
		f"Größen {[item['achsen'] for item in report['komponenten']]}")
	print(f"Bericht: {target}")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
	parser.add_argument("--out", type=Path)
	parser.add_argument("--endpoint-tolerance-m", type=float, default=0.5)
	args = parser.parse_args()
	try:
		run(directory=args.dir, output=args.out,
			tolerance_m=args.endpoint_tolerance_m)
	except (OSError, ValueError, KeyError, TypeError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
