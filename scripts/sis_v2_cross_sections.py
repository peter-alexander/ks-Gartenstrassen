"""Diagnose: stabile Voronoi-Querschnitte ab den beiden GIP-EDGE-Enden.

Schreibt nur GeoJSON und einen Bericht; verändert die Voronoi-Partition nicht.
Alle Koordinaten und Abstände intern in EPSG:31256 (Meter).
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sqlite3

from pyproj import Transformer
from shapely.geometry import LineString, Point, mapping
from shapely.ops import transform, unary_union
from shapely.wkb import loads

TO_WGS = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform
STEP_M = 1.
WINDOW = 5
TOLERANCE = .10
MIN_GROWTH = .20
MAX_SEARCH_M = 40.


def cross_section(polygon, axis, distance):
	"""Breite ausschließlich der Voronoi-Teilfläche an der EDGE-Position."""
	pos = axis.interpolate(distance)
	before = axis.interpolate(max(0., distance - .25))
	after = axis.interpolate(min(axis.length, distance + .25))
	dx, dy = after.x - before.x, after.y - before.y
	length = (dx * dx + dy * dy) ** .5
	if length < 1e-8:
		return None
	nx, ny = -dy / length, dx / length
	extent = 100.
	probe = LineString([
		(pos.x - nx * extent, pos.y - ny * extent),
		(pos.x + nx * extent, pos.y + ny * extent),
	])
	intersection = polygon.intersection(probe)
	if intersection.is_empty:
		return None
	segments = [intersection] if intersection.geom_type == "LineString" else (
		list(intersection.geoms) if hasattr(intersection, "geoms") else [])
	segments = [seg for seg in segments if seg.geom_type == "LineString" and seg.length > .01]
	# Kein benachbarter Straßenarm: nur der Querschnitt, der die Achse schneidet.
	containing = [seg for seg in segments if seg.distance(pos) < .10]
	if len(containing) != 1:
		return None
	return containing[0].length, containing[0]


def detect(widths):
	"""Erste stabile Fünferfolge nach messbarer anfänglicher Aufweitung."""
	for i in range(1, len(widths) - WINDOW + 1):
		chunk = widths[i:i + WINDOW]
		if any(w is None or w[0] < .5 for w in chunk):
			continue
		values = [w[0] for w in chunk]
		middle = sorted(values)[WINDOW // 2]
		if max(values) - min(values) > TOLERANCE * middle:
			continue
		earlier = [w[0] for w in widths[:i] if w is not None]
		if not earlier:
			continue
		# Vom NODE aus wachsende Fläche: vorher tatsächlich schmaler.
		if min(earlier) > (1 - MIN_GROWTH) * middle:
			continue
		return i
	return None


def evaluate(axis, polygon, *, reverse=False):
	if reverse:
		axis = LineString(list(axis.coords)[::-1])
	limit = min(MAX_SEARCH_M, axis.length * .45)
	if limit < WINDOW + 2:
		return {"status": "edge_zu_kurz"}, None
	widths = [cross_section(polygon, axis, float(d)) for d in range(int(limit) + 1)]
	index = detect(widths)
	profile = [{"abstand_m": d, "breite_m": round(w[0], 3) if w else None}
		for d, w in enumerate(widths)]
	if index is None:
		return {"status": "keine_stabile_grenze", "profil": profile}, None
	width, cross = widths[index]
	return {"status": "grenze_gefunden", "distanz_m": index,
		"breite_m": round(width, 3), "profil": profile}, cross


def run(gip_path, partition_path, output):
	gip_path, partition_path, output = map(Path, (gip_path, partition_path, output))
	if output.exists():
		raise FileExistsError(output)
	features = []
	stats = Counter()
	with sqlite3.connect(f"file:{gip_path.resolve()}?mode=ro", uri=True) as gip, \
			sqlite3.connect(f"file:{partition_path.resolve()}?mode=ro", uri=True) as partition:
		config = dict(partition.execute("SELECT key,value FROM config"))
		if config.get("junction_policy") != "none" or config.get("fow_policy") != "all":
			raise ValueError("Erfordert unbeschnittene GIP2-Voronoi-Aufteilung")
		# Alle Kachelstücke einer EDGE gemeinsam messen, um künstliche
		# Querschnittslücken an den Grenzen der Arbeitskacheln zu vermeiden.
		by_id = defaultdict(list)
		for gid, blob in partition.execute(
				"SELECT gip_id,geom FROM parts WHERE kind='abschnitt'"):
			by_id[gid].append(loads(blob))
		axes = {gid: geom for gid, geom in gip.execute(
			"SELECT gip,wkb FROM axes")}
		for gid, pieces in sorted(by_id.items()):
			axis_blob = axes.get(gid)
			if axis_blob is None:
				raise ValueError(f"Fehlende EDGE: {gid}")
			axis = loads(axis_blob)
			if axis.geom_type != "LineString":
				stats["multi_edge_uebersprungen"] += 1
				continue
			polygon = unary_union(pieces)
			for end, reverse in (("node_from", False), ("node_to", True)):
				result, cross = evaluate(axis, polygon, reverse=reverse)
				stats[result["status"]] += 1
				if cross is None:
					continue
				features.append({"type": "Feature",
					"properties": {
						"gip_id": gid, "ende": end,
						"abstand_m": result["distanz_m"],
						"breite_m": result["breite_m"],
						"messabstand_m": STEP_M, "fenster": WINDOW,
						"breitentoleranz": TOLERANCE,
						"mindestens_zunahme": MIN_GROWTH,
						"breitenprofil": json.dumps(result["profil"], ensure_ascii=False),
					},
					"geometry": mapping(transform(TO_WGS, cross))})
	output.parent.mkdir(parents=True, exist_ok=True)
	output.write_text(json.dumps({"type": "FeatureCollection", "features": features},
		ensure_ascii=False), encoding="utf-8")
	report = {"status": "Nur Diagnoselinien; keine Flächen ausgeschnitten",
		"achsen_mit_voronoi_flaeche": len(by_id), "schnittlinien": len(features),
		"ergebnisse": dict(stats), "messabstand_m": STEP_M, "fenster": WINDOW,
		"breitentoleranz": TOLERANCE, "mindestens_zunahme": MIN_GROWTH,
		"maximaler_suchabstand_m": MAX_SEARCH_M}
	output.with_suffix(".bericht.json").write_text(
		json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--gip-index", required=True, type=Path)
	parser.add_argument("--partition-db", required=True, type=Path)
	parser.add_argument("--out", required=True, type=Path)
	args = parser.parse_args()
	print(json.dumps(run(args.gip_index, args.partition_db, args.out),
		ensure_ascii=False, indent=2))


if __name__ == "__main__":
	main()
