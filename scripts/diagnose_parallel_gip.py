"""Read-only diagnosis of approximately parallel GIP axes in an existing index.

A 20 m two-sided buffer checks coverage (as in the RgE analysis); sampled
local tangents reject incidental proximity at perpendicular intersections.
Nothing in the Voronoi partition or GIP source index is modified.
"""
import argparse
from dataclasses import dataclass
from functools import lru_cache
import json
import math
from pathlib import Path
import sqlite3
from urllib.parse import quote

from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import mapping
from shapely.ops import transform
from shapely.wkb import loads

DISTANCE_M = 20.0
SHORT_COVER = 0.85
LONG_COVER = 0.60
MAX_ANGLE_DEG = 25.0
SPACING_M = 5.0
TO_WGS = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform


@dataclass(frozen=True)
class Axis:
	id: str
	name: str
	fow: int | None
	start: str
	end: str
	geom: object


def _parts(geom):
	return (geom,) if geom.geom_type == "LineString" else tuple(geom.geoms)


def _tangent(line, distance):
	# Symmetric local tangent, also for reversed digitization of an axis.
	window = min(3.0, line.length / 4)
	first = line.interpolate(max(0.0, distance - window))
	last = line.interpolate(min(line.length, distance + window))
	dx, dy = last.x - first.x, last.y - first.y
	norm = math.hypot(dx, dy)
	return (dx / norm, dy / norm) if norm > 1e-9 else None


def _aligned_fraction(left, right, *, distance_m, angle_deg, spacing_m):
	parts = _parts(right)
	aligned = 0.0
	for line in _parts(left):
		count = max(1, math.ceil(line.length / spacing_m))
		weight = line.length / count
		for i in range(count):
			position = (i + 0.5) * weight
			point = line.interpolate(position)
			other = min(parts, key=lambda part: part.distance(point))
			if other.distance(point) > distance_m:
				continue
			a, b = _tangent(line, position), _tangent(other, other.project(point))
			if a is None or b is None:
				continue
			cosine = min(1.0, abs(a[0] * b[0] + a[1] * b[1]))
			if math.degrees(math.acos(cosine)) <= angle_deg:
				aligned += weight
	return aligned / left.length


def _cover_ratio(geom, buffered_other):
	return min(1.0, geom.intersection(buffered_other).length / geom.length)


def find_parallel_pairs(axes, *, distance_m=DISTANCE_M, min_short=SHORT_COVER,
		min_long=LONG_COVER, angle_deg=MAX_ANGLE_DEG, spacing_m=SPACING_M):
	"""Return (pairs, number of spatial candidates) with deterministic ordering."""
	if not axes:
		return [], 0
	for value, name in ((distance_m, "distance_m"), (spacing_m, "spacing_m")):
		if not math.isfinite(value) or value <= 0:
			raise ValueError(f"{name} muss positiv und endlich sein")
	for value, name in ((min_short, "min_short"), (min_long, "min_long")):
		if not 0 < value <= 1:
			raise ValueError(f"{name} muss zwischen 0 und 1 liegen")
	if not 0 <= angle_deg < 90:
		raise ValueError("angle_deg muss zwischen 0 und 90 liegen")
	geoms = [a.geom for a in axes]
	tree = STRtree(geoms)

	@lru_cache(maxsize=256)
	def buffered(index):
		return geoms[index].buffer(distance_m)

	pairs, candidate_count = [], 0
	for i, a in enumerate(axes):
		for j_value in tree.query(a.geom, predicate="dwithin", distance=distance_m):
			j = int(j_value)
			if j <= i:
				continue
			b = axes[j]
			if a.id == b.id:
				continue
			candidate_count += 1
			cover_a = _cover_ratio(a.geom, buffered(j))
			cover_b = _cover_ratio(b.geom, buffered(i))
			short, long = (i, j) if a.geom.length <= b.geom.length else (j, i)
			if (cover_a if short == i else cover_b) < min_short:
				continue
			if (cover_a if long == i else cover_b) < min_long:
				continue
			angle_a = _aligned_fraction(a.geom, b.geom,
				distance_m=distance_m, angle_deg=angle_deg, spacing_m=spacing_m)
			if angle_a < (min_short if short == i else min_long):
				continue
			angle_b = _aligned_fraction(b.geom, a.geom,
				distance_m=distance_m, angle_deg=angle_deg, spacing_m=spacing_m)
			if angle_b < (min_short if short == j else min_long):
				continue
			pairs.append({
				"a": a.id, "b": b.id, "distance_min_m": round(a.geom.distance(b.geom), 3),
				"cover_a": round(cover_a, 4), "cover_b": round(cover_b, 4),
				"aligned_a": round(angle_a, 4), "aligned_b": round(angle_b, 4),
				"same_name": bool(a.name.strip()) and a.name.strip().casefold() == b.name.strip().casefold(),
				"shared_node": bool({a.start, a.end} & {b.start, b.end}),
				"fow_a": a.fow, "fow_b": b.fow,
			})
	return sorted(pairs, key=lambda pair: (pair["a"], pair["b"])), candidate_count


def _groups(pairs):
	parent = {}

	def find(x):
		parent.setdefault(x, x)
		if parent[x] != x:
			parent[x] = find(parent[x])
		return parent[x]

	for pair in pairs:
		a, b = find(pair["a"]), find(pair["b"])
		parent[max(a, b)] = min(a, b)
	groups = {}
	for item in parent:
		groups.setdefault(find(item), []).append(item)
	return [sorted(group) for group in sorted(groups.values(), key=lambda g: min(g))]


def read_axes(index):
	path = Path(index).resolve()
	if not path.is_file():
		raise FileNotFoundError(path)
	with sqlite3.connect("file:" + quote(str(path), safe="/") + "?mode=ro", uri=True) as db:
		try:
			row = db.execute("SELECT value FROM meta WHERE key='crs'").fetchone()
			if row and json.loads(row[0]) != "EPSG:31256":
				raise ValueError("GIP-Index benötigt EPSG:31256")
			rows = db.execute("SELECT gip,name,fow,node_from,node_to,wkb FROM axes ORDER BY gip")
			result = []
			for gid, name, fow, start, end, wkb in rows:
				geom = loads(wkb)
				if geom.geom_type not in ("LineString", "MultiLineString") or geom.is_empty or geom.length <= 0:
					raise ValueError(f"GIP-Achse {gid}: keine gültige Linie")
				result.append(Axis(str(gid), str(name or ""), fow, str(start), str(end), geom))
			return result
		except sqlite3.OperationalError as exc:
			raise ValueError("Kein kompatibler GIP-Index (axes/meta benötigt)") from exc


def run(index, output, *, distance_m=DISTANCE_M):
	output = Path(output)
	json_file = output / "parallelpaare.json"
	geo_file = output / "parallelpaare.geojson"
	if json_file.exists() or geo_file.exists():
		raise FileExistsError("Diagnoseausgaben existieren bereits; nicht überschreiben")
	axes = read_axes(index)
	pairs, candidates = find_parallel_pairs(axes, distance_m=distance_m)
	groups = _groups(pairs)
	group_by_id = {gid: i + 1 for i, group in enumerate(groups) for gid in group}
	by_id = {axis.id: axis for axis in axes}
	result = {
		"schema_version": 1, "status": "nur_diagnose_keine_vereinigung",
		"input_index": str(Path(index).resolve()), "achsen": len(axes),
		"parameter": {"max_distance_m": distance_m, "min_cover_short": SHORT_COVER,
			"min_cover_long": LONG_COVER, "max_angle_deg": MAX_ANGLE_DEG,
			"direction_sample_spacing_m": SPACING_M},
		"raumliche_kandidaten": candidates, "akzeptierte_paare": len(pairs),
		"gruppen": [{"gruppe": i + 1, "gip_ids": g} for i, g in enumerate(groups)],
		"paare": pairs,
	}
	output.mkdir(parents=True, exist_ok=True)
	json_file.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	features = []
	for i, pair in enumerate(pairs, start=1):
		for role in ("a", "b"):
			axis = by_id[pair[role]]
			features.append({"type": "Feature", "geometry": mapping(transform(TO_WGS, axis.geom)),
				"properties": {"paar": i, "gruppe": group_by_id[axis.id],
					"rolle": role, "gip_id": axis.id, "name": axis.name,
					"fow": axis.fow, "gegenkante": pair["b" if role == "a" else "a"],
					"deckungsgrad": pair["cover_" + role],
					"parallelanteil": pair["aligned_" + role]}})
	geo_file.write_text(json.dumps({"type": "FeatureCollection", "features": features},
		ensure_ascii=False) + "\n", encoding="utf-8")
	return result


def main():
	parser = argparse.ArgumentParser(description="Parallele GIP-Achsen prüfen; keine produktive Vereinigung")
	parser.add_argument("--gip-index", type=Path, required=True, help="Vorhandene gip.sqlite in EPSG:31256")
	parser.add_argument("--out-dir", type=Path, required=True, help="Separates Ausgabeverzeichnis")
	parser.add_argument("--distance-m", type=float, default=DISTANCE_M)
	args = parser.parse_args()
	result = run(args.gip_index, args.out_dir, distance_m=args.distance_m)
	print(f"GIP-Parallelprüfung: {result['achsen']} Achsen, "
		f"{result['raumliche_kandidaten']} Nähepaare, "
		f"{result['akzeptierte_paare']} parallele Paare, "
		f"{len(result['gruppen'])} Diagnosegruppen")


if __name__ == "__main__":
	main()
