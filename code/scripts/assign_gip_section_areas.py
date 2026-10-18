#!/usr/bin/env python3
"""Modul 5: EXPERIMENTELLE exklusive Straßenraum-Aufteilung nach GIP-Achsen.

Flächentreuer Schnitt der vorhandenen Modul-2-Straßenmaske:
1. Kreuzungsknoten (Graph-Grad >= 3) erhalten eigene Prüfflächen.
2. Dicht abgetastete GIP-Achsen liefern Punkt-Voronoi-Zellen.
3. Nur Zellen im Abstand <= max_axis_distance_m von ihrer Quellachse
   werden zugeordnet; FOW != 3 bleibt als Sonderweg ungeklärt.
4. Sämtliche Restflächen werden ausdrücklich gespeichert.

Weder die amtliche GIP-Straßenachse noch die Voronoi-Grenze ist eine
amtliche Verkehrsflächenabgrenzung. Keine Abschnitts-Kennzahlen hier.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from pyproj import Transformer
from shapely import union_all, voronoi_polygons
from shapely.geometry import MultiPoint, Polygon, MultiPolygon, box, mapping, shape
from shapely.ops import transform

from scripts.analyze_gpkg import polygonal_part
from scripts.analyze_gip_topology import audit, read_geojson
from scripts.fmzk_source import load_polygons
from scripts.measure_ground_greening import load_street_mask

DEFAULT_FMZK = Path("data/processed/fmzk_test.gpkg")
DEFAULT_STREET = Path("data/processed/street_space/fmzk_strassenraum.geojson")
DEFAULT_GIP = Path("data/processed/strassenabschnitte/gip")
DEFAULT_OUTPUT = Path("data/processed/strassenabschnitte/aufteilung_v0")
METRIC = Transformer.from_crs(
	"EPSG:4326", "EPSG:31256", always_xy=True).transform
LONLAT = Transformer.from_crs(
	"EPSG:31256", "EPSG:4326", always_xy=True).transform
DEFAULT_SPACING_M = 5
DEFAULT_NODE_RADIUS_M = 7
DEFAULT_MAX_DISTANCE_M = 25
MAX_SITES = 10000
AREA_TOLERANCE_M2 = 0.05


def positive(value, label, *, min_value, max_value):
	if not isinstance(value, (float, int)) or not math.isfinite(value) or not (
		min_value <= value <= max_value
	):
		raise ValueError(f"{label} muss zwischen {min_value} und {max_value} liegen")
	return float(value)


def polygon_part(geometry, *, label):
	if geometry is None or geometry.is_empty or geometry.area <= 0:
		return None
	if not geometry.is_valid:
		raise ValueError(f"{label}: ungültige polygonale Geometrie")
	poly = polygonal_part(geometry)
	if poly is None or poly.is_empty or poly.area <= 0 or not poly.is_valid:
		raise ValueError(f"{label}: nichtpolygonale oder ungültige Fläche")
	return poly


def prepare_graph(axis_features, node_features):
	"""Geprüfte Karten-Geometrien in EPSG:31256 und eindeutige IDs bringen."""
	axes = []
	seen = set()
	for item in axis_features:
		props = item["properties"]
		identifier = str(props["gip_objectid"])
		if identifier in seen:
			raise ValueError(f"Doppelte GIP-Achsen-ID {identifier}; vorher prüfen")
		seen.add(identifier)
		geom = transform(METRIC, shape(item["geometry"]))
		if geom.geom_type != "LineString" or not geom.is_valid or geom.length <= 0:
			raise ValueError(f"Achse {identifier}: ungültige LineString-Geometrie")
		axes.append({
			"id": identifier, "name": props.get("name") or "",
			"fow": props.get("fow"),
			"geometry": geom, "start": str(props["node_from"]),
			"end": str(props["node_to"]),
		})
	nodes = []
	seen.clear()
	for item in node_features:
		props = item["properties"]
		identifier = str(props["gip_objectid"])
		if identifier in seen:
			raise ValueError(f"Doppelte GIP-Knoten-ID {identifier}")
		seen.add(identifier)
		geom = transform(METRIC, shape(item["geometry"]))
		if geom.geom_type != "Point" or not geom.is_valid:
			raise ValueError(f"Knoten {identifier}: ungültige Punktgeometrie")
		nodes.append({"id": identifier, "name": props.get("name") or "",
			"geometry": geom})
	return axes, nodes


def _samples(axes, spacing_m):
	"""Eindeutig geordnete, innenliegende Stützpunkte statt gleicher Knoten."""
	coordinates = []
	owners = []
	seen = {}
	for axis_index, axis in enumerate(axes):
		line = axis["geometry"]
		count = max(1, math.ceil(line.length / spacing_m))
		if len(coordinates) + count > MAX_SITES:
			raise ValueError(f"Über {MAX_SITES} GIP-Stützpunkte; "
				"für diesen Testausschnitt größere --sample-spacing-m verwenden")
		for number in range(count):
			point = line.interpolate((number + 0.5) / count, normalized=True)
			x, y = point.coords[0]
			key = round(x, 3), round(y, 3)
			if key in seen:
				raise ValueError(
					f"Deckungsgleiche Achs-Stützpunkte bei {key}: "
					f"{axes[seen[key]]['id']} und {axis['id']}; "
					"mehrdeutige Quellgeometrie, nicht automatisch zuweisen")
			seen[key] = axis_index
			coordinates.append((x, y))
			owners.append(axis_index)
	return coordinates, owners


def partition(street, axes, nodes, *, spacing_m=DEFAULT_SPACING_M,
	node_radius_m=DEFAULT_NODE_RADIUS_M,
	max_distance_m=DEFAULT_MAX_DISTANCE_M):
	"""Partitioniert metrische Straßenfläche ohne Verlust oder Doppelzählung.

	axes: [{id,name,fow,geometry(LineString),start,end}], nodes:
	[{id,name,geometry(Point)}], jeweils EPSG:31256.
	"""
	spacing_m = positive(spacing_m, "Stützpunkt-Abstand",
		min_value=1, max_value=50)
	node_radius_m = positive(node_radius_m, "Knotenradius",
		min_value=1, max_value=25)
	max_distance_m = positive(max_distance_m, "Maximaler Achsabstand",
		min_value=5, max_value=80)
	if not isinstance(street, (Polygon, MultiPolygon)) or (
		street.is_empty or not street.is_valid or street.area <= 0
	):
		raise ValueError("Straßenraum muss eine gültige Polygonfläche sein")
	if not axes or not nodes:
		raise ValueError("GIP-Achsen und -Knoten fehlen")
	degree = Counter()
	for axis in axes:
		if axis["geometry"].geom_type != "LineString":
			raise ValueError(f"Achse {axis['id']}: keine LineString")
		degree[str(axis["start"])] += 1
		degree[str(axis["end"])] += 1
	junction_nodes = [node for node in nodes
		if degree[str(node["id"])] >= 3]
	buffers = [node["geometry"].buffer(node_radius_m, resolution=12)
		for node in junction_nodes]
	junction_area = polygon_part(
		union_all(buffers).intersection(street) if buffers else None,
		label="Knotenbereiche")
	remaining = street
	unresolved = []
	if junction_area is not None:
		unresolved.append(("knotenbereich", junction_area))
		remaining = remaining.difference(junction_area)
	coordinates, owners = _samples(axes, spacing_m)
	if len(coordinates) < 2:
		raise ValueError("Zu wenige GIP-Stützpunkte für Voronoi-Aufteilung")
	# GEOS >=3.12 liefert mit ordered=True die Zellen in Punktreihenfolge.
	# Voraussetzung in requirements-analysis.txt: Shapely 2.1.2.
	cells = voronoi_polygons(MultiPoint(coordinates),
		extend_to=street.envelope.buffer(max_distance_m),
		ordered=True)
	if len(cells.geoms) != len(coordinates):
		raise ValueError("GIP-Voronoi lieferte unvollständige Zellzuordnung")
	by_axis = defaultdict(list)
	for idx, cell in enumerate(cells.geoms):
		by_axis[owners[idx]].append(cell)
	sections = []
	special_parts = []
	for idx, axis in enumerate(axes):
		candidate = polygon_part(
			union_all(by_axis[idx]).intersection(remaining),
			label=f"Voronoi {axis['id']}")
		if candidate is None:
			continue
		# Begrenzung ist eine technische Plausibilitätsgrenze, keine
		# vermessene Fahrbahnbreite.
		near = polygon_part(candidate.intersection(
			axis["geometry"].buffer(max_distance_m, resolution=8)),
			label=f"Achsnähe {axis['id']}")
		if near is None:
			continue
		near = polygon_part(near.intersection(remaining),
			label=f"Exklusive Fläche {axis['id']}")
		if near is None:
			continue
		remaining = remaining.difference(near)
		if axis["fow"] != 3:
			special_parts.append(near)
		else:
			sections.append((axis, near))
	if special_parts:
		special = polygon_part(union_all(special_parts),
			label="Sonderachsen")
		unresolved.append(("sonderachse", special))
	rest = polygon_part(remaining, label="Restflächen")
	if rest is not None:
		unresolved.append(("nicht_zugeordnet", rest))
	assigned_area = sum(geometry.area for _, geometry in sections)
	unresolved_area = sum(geometry.area for _, geometry in unresolved)
	total = assigned_area + unresolved_area
	union = union_all(
		[geometry for _, geometry in sections] +
		[geometry for _, geometry in unresolved])
	tolerance = max(AREA_TOLERANCE_M2, street.area * 1e-6)
	overlap = max(0, total - union.area)
	missing = street.difference(union).area
	outside = union.difference(street).area
	if any(value > tolerance for value in (
		abs(total - street.area), overlap, missing, outside,
	)):
		raise ValueError(
			f"Straßenraum-Flächenbilanz fehlerhaft: "
			f"Gesamtdifferenz {total-street.area:.6f}, "
			f"Überlappung {overlap:.6f}, Lücke {missing:.6f}, "
			f"außerhalb {outside:.6f} m²")
	return sections, unresolved, {
		"strassenraum_m2": street.area,
		"zugeordnet_m2": assigned_area,
		"ungeklaert_m2": unresolved_area,
		"gesamt_m2": total,
		"bilanzdifferenz_m2": total - street.area,
		"ueberlappung_m2": overlap, "fehlend_m2": missing,
		"ausserhalb_m2": outside,
		"toleranz_m2": tolerance,
		"anzahl_zugeordnete_abschnitte": len(sections),
		"anzahl_achsen": len(axes),
		"anzahl_kreuzungsknoten": len(junction_nodes),
		"anzahl_voronoi_stuetzpunkte": len(coordinates),
		"ungeklaert_nach_typ_m2": {key: geom.area
			for key, geom in unresolved},
		"fow_haeufigkeit": dict(Counter(str(axis["fow"])
			for axis in axes)),
	}


def as_feature(geometry, *, fid, properties):
	return {"type": "Feature", "id": fid,
		"properties": properties,
		"geometry": mapping(transform(LONLAT, geometry))}


def _write_json(path, data):
	path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
		encoding="utf-8")


def run(street=DEFAULT_STREET, fmzk=DEFAULT_FMZK, gip=DEFAULT_GIP,
	output=DEFAULT_OUTPUT, *, spacing_m=DEFAULT_SPACING_M,
	node_radius_m=DEFAULT_NODE_RADIUS_M,
	max_distance_m=DEFAULT_MAX_DISTANCE_M):
	output = Path(output)
	targets = {
		"abschnitte": output / "abschnitte_flaechen.geojson",
		"ungeklaert": output / "abschnitte_ungeklaert.geojson",
		"bericht": output / "abschnitte_bericht.json",
	}
	if any(path.exists() for path in targets.values()):
		raise FileExistsError(
			f"Ausgabe unter {output} existiert schon; anderes --out-dir verwenden")
	_, fmzk_manifest, clip, _ = load_polygons(fmzk)
	street_geom, street_meta = load_street_mask(street, clip)
	gip = Path(gip)
	probe_path = gip / "gip_probe_bericht.json"
	probe = json.loads(probe_path.read_text(encoding="utf-8"))
	if probe.get("fmzk_bbox_lon_lat") != fmzk_manifest.get("bbox_lon_lat"):
		raise ValueError("GIP- und Straßenraum-Testgebiet haben verschiedene BBOX")
	axis_path = gip / "abschnitte_achsen.geojson"
	node_path = gip / "abschnitte_knoten.geojson"
	axis_features = read_geojson(axis_path, label="GIP-Achsen")
	node_features = read_geojson(node_path, label="GIP-Knoten")
	topology = audit(axis_features, node_features, probe)
	if topology["status"] != "topologie_konsistent":
		raise ValueError("GIP-Topologie hat offene Fehler; "
			"vor der Flächenzuordnung prüfen")
	axes, nodes = prepare_graph(axis_features, node_features)
	sections, unresolved, stats = partition(
		street_geom, axes, nodes, spacing_m=spacing_m,
		node_radius_m=node_radius_m,
		max_distance_m=max_distance_m)
	output_sections = {"type": "FeatureCollection", "features": [
		as_feature(geometry, fid=f"gip:{axis['id']}",
			properties={"gip_objectid": axis["id"],
				"name": axis["name"], "fow": axis["fow"],
				"status": "experimentell_achsennaehe",
				"flaeche_m2": geometry.area})
		for axis, geometry in sections
	]}
	output_unresolved = {"type": "FeatureCollection", "features": [
		as_feature(geometry, fid=f"ungeklaert:{name}",
			properties={"status": name, "flaeche_m2": geometry.area})
		for name, geometry in unresolved
	]}
	report = {
		"schema_version": 1,
		"created_utc": datetime.now(timezone.utc).isoformat(),
		"status": "EXPERIMENTELL – NICHT VALIDIERTE STRASSENABSCHNITTE",
		"parameter": {
			"sample_spacing_m": spacing_m,
			"knotenradius_m": node_radius_m,
			"max_axis_distance_m": max_distance_m,
			"gip_standard_fow": 3,
		},
		"quelle": {
			"strassenraum_geojson": str(street),
			"strassenraum_sha256": street_meta["masken_sha256"],
			"fmzk": str(fmzk),
			"gip_achsen": str(axis_path),
			"gip_achsen_sha256": hashlib.sha256(axis_path.read_bytes()).hexdigest(),
			"gip_knoten": str(node_path),
			"gip_knoten_sha256": hashlib.sha256(node_path.read_bytes()).hexdigest(),
			"gip_probe_bericht": str(probe_path),
		},
		"bilanz": stats,
		"hinweis": (
			"Voronoi-Zuordnung ist ein geometrischer Versuch: kein "
			"amtlicher Fahrbahnrand und keine fachlich geprüfte "
			"Straßenabschnittsklassifikation. Knotenbereiche, FOW != 3 "
			"und Restflächen bleiben separat. Keine Baumkronen- oder "
			"Bodenbegrünungsquote pro Abschnitt berechnet."
		),
		"ausgaben": {k: str(v) for k, v in targets.items()},
	}
	# Ausgabedateien erst nach vollständiger Geometrievalidierung erstellen.
	output.mkdir(parents=True, exist_ok=True)
	_write_json(targets["abschnitte"], output_sections)
	_write_json(targets["ungeklaert"], output_unresolved)
	_write_json(targets["bericht"], report)
	print(f"Straßenraum: {street_geom.area:.2f} m²")
	print(f"Zugeteilt: {stats['zugeordnet_m2']:.2f} m² in "
		f"{stats['anzahl_zugeordnete_abschnitte']} Abschnitten")
	print(f"Ungeklärt: {stats['ungeklaert_m2']:.2f} m²; "
		f"Bilanzdifferenz {stats['bilanzdifferenz_m2']:.6f} m²")
	print(f"Bericht: {targets['bericht']}")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--street-geojson", type=Path, default=DEFAULT_STREET)
	parser.add_argument("--fmzk", type=Path, default=DEFAULT_FMZK)
	parser.add_argument("--gip-dir", type=Path, default=DEFAULT_GIP)
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
	parser.add_argument("--sample-spacing-m", type=float, default=DEFAULT_SPACING_M)
	parser.add_argument("--node-radius-m", type=float, default=DEFAULT_NODE_RADIUS_M)
	parser.add_argument("--max-axis-distance-m", type=float,
		default=DEFAULT_MAX_DISTANCE_M)
	args = parser.parse_args()
	try:
		run(street=args.street_geojson, fmzk=args.fmzk, gip=args.gip_dir,
			output=args.out_dir, spacing_m=args.sample_spacing_m,
			node_radius_m=args.node_radius_m,
			max_distance_m=args.max_axis_distance_m)
	except (OSError, ValueError, TypeError, KeyError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
