"""Kürzt GIP2-Voronoi-Abschnitte an der ersten stabilen Querschnittsbreite.

Schreibt eine neue Partition, mit unveränderten Quellflächen und voller Bilanz.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sqlite3

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union
from shapely.wkb import dumps, loads

from scripts.sis_v2_cross_sections import evaluate, STEP_M, WINDOW, TOLERANCE, MIN_GROWTH, MAX_SEARCH_M


def cut_mask(axis, distance, bounds, reverse=False):
	if reverse:
		axis = LineString(list(axis.coords)[::-1])
	p = axis.interpolate(distance)
	a = axis.interpolate(max(0., distance - .25))
	b = axis.interpolate(min(axis.length, distance + .25))
	dx, dy = b.x - a.x, b.y - a.y
	length = (dx * dx + dy * dy) ** .5
	if length < 1e-8:
		return None
	tx, ty = dx / length, dy / length
	nx, ny = -ty, tx
	x0, y0, x1, y1 = bounds
	size = max(x1 - x0, y1 - y0, axis.length, 100.) * 3
	return Polygon([
		(p.x + nx * size, p.y + ny * size),
		(p.x - nx * size, p.y - ny * size),
		(p.x - nx * size - tx * size, p.y - ny * size - ty * size),
		(p.x + nx * size - tx * size, p.y + ny * size - ty * size),
	])


def run(gip_index, source_partition, output):
	gip_index, source_partition, output = map(Path,
		(gip_index, source_partition, output))
	if output.exists():
		raise FileExistsError(output)
	temp = output.with_suffix(".tmp")
	if temp.exists():
		raise FileExistsError(temp)
	output.parent.mkdir(parents=True, exist_ok=True)
	stats = Counter()
	try:
		with sqlite3.connect(f"file:{gip_index.resolve()}?mode=ro", uri=True) as gip, \
				sqlite3.connect(f"file:{source_partition.resolve()}?mode=ro", uri=True) as src, \
				sqlite3.connect(temp) as dst:
			config = dict(src.execute("SELECT key,value FROM config"))
			if config.get("junction_policy") != "none" or config.get("fow_policy") != "all":
				raise ValueError("Erfordert unbeschnittene Voronoi-Partition mit allen EDGE")
			method = json.loads(gip.execute("SELECT value FROM meta "
				"WHERE key='index_method'").fetchone()[0])
			if method != "gip2-local-edge-turn-use-v1":
				raise ValueError("Querschnittsversuch benötigt lokalen GIP2-Index")
			src.backup(dst)
			by_id = defaultdict(list)
			for gid, blob in src.execute("SELECT gip_id,geom FROM parts "
					"WHERE kind='abschnitt'"):
				by_id[gid].append(loads(blob))
			axes = dict(gip.execute("SELECT gip,wkb FROM axes"))
			masks = {}
			for gid, pieces in sorted(by_id.items()):
				if gid not in axes:
					raise ValueError(f"Fehlende GIP-EDGE {gid}")
				axis = loads(axes[gid])
				if axis.geom_type != "LineString":
					stats["multi_edge_uebersprungen"] += 1
					continue
				polygon = unary_union(pieces)
				candidates = []
				for reverse in (False, True):
					result, cross = evaluate(axis, polygon, reverse=reverse)
					stats[result["status"]] += 1
					if cross is None:
						continue
					mask = cut_mask(axis, result["distanz_m"],
						polygon.bounds, reverse=reverse)
					if mask is not None and polygon.intersection(mask).area > .01:
						candidates.append(mask)
				if not candidates:
					continue
				mask = unary_union(candidates)
				left = polygon.difference(mask)
				if left.area < .01:
					stats["vollstaendiger_abschnitt_verworfen"] += 1
					continue
				if not left.is_valid:
					stats["ungueltiger_schnitt_verworfen"] += 1
					continue
				masks[gid] = mask
				stats["achsen_mit_schnitt"] += 1
			removed_total = 0.
			for (tid,) in dst.execute("SELECT id FROM tiles").fetchall():
				rows = dst.execute("SELECT gip_id,area,geom FROM parts "
					"WHERE tile_id=? AND kind='abschnitt'", (tid,)).fetchall()
				cut_parts = []
				cut_area = 0.
				for gid, area, blob in rows:
					mask = masks.get(gid)
					if mask is None:
						continue
					poly = loads(blob)
					cut = poly.intersection(mask)
					if cut.area < 1e-7:
						continue
					keep = poly.difference(mask)
					if not keep.is_valid or not cut.is_valid:
						raise ValueError(f"{tid}/{gid}: ungültiger Schnitt")
					if abs(keep.area + cut.area - area) > max(.01, area * 1e-8):
						raise ValueError(f"{tid}/{gid}: fehlerhafte Schnittbilanz")
					cut_parts.append(cut)
					cut_area += cut.area
					if keep.area < 1e-7:
						dst.execute("DELETE FROM parts WHERE tile_id=? "
							"AND kind='abschnitt' AND gip_id=?", (tid, gid))
					else:
						dst.execute("UPDATE parts SET area=?,geom=? "
							"WHERE tile_id=? AND kind='abschnitt' AND gip_id=?",
							(keep.area, dumps(keep), tid, gid))
				if not cut_parts:
					continue
				old = dst.execute("SELECT geom FROM parts WHERE tile_id=? "
					"AND kind='ungeklaert' AND gip_id='knotenbereich'",
					(tid,)).fetchone()
				if old:
					cut_parts.append(loads(old[0]))
				merged = unary_union(cut_parts)
				if not merged.is_valid:
					raise ValueError(f"{tid}: ungültige Kreuzungsfläche")
				dst.execute("INSERT OR REPLACE INTO parts VALUES (?,?,?,?,?)",
					(tid, "ungeklaert", "knotenbereich", merged.area, dumps(merged)))
				row = dst.execute("SELECT assigned,unresolved,stats_json FROM tiles "
					"WHERE id=?", (tid,)).fetchone()
				assigned, unresolved, raw_stats = row
				tile_stats = json.loads(raw_stats)
				tile_stats["zugeordnet_m2"] = assigned - cut_area
				tile_stats["ungeklaert_m2"] = unresolved + cut_area
				tile_stats["querschnitt_ausgeschnitten_m2"] = cut_area
				dst.execute("UPDATE tiles SET assigned=?,unresolved=?,stats_json=? "
					"WHERE id=?", (assigned - cut_area, unresolved + cut_area,
						json.dumps(tile_stats, ensure_ascii=False), tid))
				removed_total += cut_area
			dst.execute("UPDATE config SET value=? WHERE key='junction_policy'",
				("voronoi-stable-width-v1",))
			dst.execute("INSERT INTO config VALUES ('querschnitt_regel',?)",
				(json.dumps({"step_m":STEP_M,"fenster":WINDOW,
					"toleranz":TOLERANCE,"mindestzunahme":MIN_GROWTH,
					"suchweite_m":MAX_SEARCH_M}),))
			if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
				raise ValueError("SQLite-Integritätsprüfung fehlgeschlagen")
			dst.commit()
		temp.replace(output)
	except BaseException:
		temp.unlink(missing_ok=True)
		raise
	return {"geschnittene_flaeche_m2":removed_total,
		"achsen_mit_voronoi":len(by_id), "statistik":dict(stats)}


def main():
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("--gip-index",type=Path,required=True)
	p.add_argument("--partition-db",type=Path,required=True)
	p.add_argument("--out",type=Path,required=True)
	a = p.parse_args()
	print(json.dumps(run(a.gip_index,a.partition_db,a.out),
		ensure_ascii=False,indent=2))


if __name__ == "__main__":
	main()
