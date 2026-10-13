"""Methode B: Wien/OSM-Merge aus kartensammlung-overlay-builds/baumkataster.

Port der tatsächlich verwendeten Merge-Priorität, Abstände und Baumreihen-
Positionierung (baumkataster/build.mjs, geprüft 14.10.2026).
Die Kartensammlung zeichnet diese Punkte als MapLibre-Kreise; wir erzeugen
stattdessen metrische Kronen-Polygone für die Flächenberechnung.

Besonderheit der 2D-Analyse: Die Lageprüfung erfolgt in EPSG:31256 statt
über die vereinfachte lokale WGS84-Meterskalierung des Tile-Builders.
Die fehlenden OSM-Kronendurchmesser verwenden transparent gekennzeichnete
SolarViennaTrees-Schätzwerte (Höhe × 0,5, Default-Höhe 12 m).
"""

from collections import Counter
import math
import re

from pyproj import Transformer
from shapely.geometry import Point

WFS_OSM_DEDUP_M = 4.0
OSM_NODE_DEDUP_M = 0.75
ROW_EXPLICIT_DEDUP_M = 4.0
ROW_ROW_DEDUP_M = 3.0
ROW_SPACING_M = 8.0
MAX_ROW_SAMPLES = 500
MAX_CROWN_DIAMETER_M = 50.0

_TO_METRIC = Transformer.from_crs("EPSG:4326", "EPSG:31256", always_xy=True)


def metric_point(lon, lat):
	if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (lon, lat)):
		raise ValueError("Ungültige Baumstandort-Koordinaten")
	if not (15.5 <= lon <= 17.0 and 47.7 <= lat <= 48.6):
		raise ValueError("Baumstandort liegt außerhalb des Wiener Bereichs")
	return Point(*_TO_METRIC.transform(lon, lat))


class PointGrid:
	"""4-m-Rasterindex nach kartensammlung-overlay-builds; Prüfkoordinaten metrisch."""
	def __init__(self, cell=4.0):
		self.cell = cell
		self.cells = {}

	def add(self, point, identifier=None):
		key = self.key(point)
		self.cells.setdefault(key, []).append((point, identifier))

	def key(self, point):
		return (math.floor(point.x / self.cell), math.floor(point.y / self.cell))

	def near(self, point, radius):
		if radius < 0:
			raise ValueError("Abstand darf nicht negativ sein")
		x, y = self.key(point)
		span = math.ceil(radius / self.cell)
		near = []
		for dx in range(-span, span + 1):
			for dy in range(-span, span + 1):
				for other, identifier in self.cells.get((x + dx, y + dy), []):
					distance = point.distance(other)
					if distance <= radius:
						near.append((distance, identifier))
		return min(near, default=None, key=lambda item: item[0])


def parse_osm_metres(value):
	"""Bekannte OSM-Längeneinheiten eindeutig lesen; keine impliziten Textzahlen."""
	if value is None or isinstance(value, bool):
		return None
	text = str(value).strip().lower().replace(",", ".")
	m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(m|cm|mm|ft|feet|foot)?", text)
	if m is None:
		return None
	n = float(m[1])
	unit = m[2] or "m"
	factor = {"m": 1, "cm": 0.01, "mm": 0.001, "ft": 0.3048,
		"feet": 0.3048, "foot": 0.3048}[unit]
	return n * factor if n > 0 and math.isfinite(n) else None


def osm_crown_diameter(tags, *, allow_estimates=True):
	"""Gemessenen OSM-Kronendurchmesser bevorzugen, Solar-Fallback optional."""
	for field in ("diameter_crown", "crown:diameter", "crown_diameter"):
		if field not in tags:
			continue
		diameter = parse_osm_metres(tags[field])
		if diameter is not None and 0 < diameter <= MAX_CROWN_DIAMETER_M:
			return diameter, "osm_expliziter_kronendurchmesser", field, None
	if not allow_estimates:
		return None, "osm_durchmesser_unbekannt", None, None
	height = parse_osm_metres(tags.get("height"))
	if height is None or not 1.5 <= height <= 45:
		height = 12.0
		quality = "solar_default_hoehe_12m"
	else:
		quality = "solar_geschaetzt_aus_osm_hoehe"
	# SolarViennaTrees: clamp(height*0.5, 2, 12), dann height*1.2.
	diameter = min(max(height * 0.5, 2.0), 12.0)
	diameter = min(max(diameter, 1.0), min(25.0, height * 1.2))
	return diameter, quality, "height" if quality == "solar_geschaetzt_aus_osm_hoehe" else None, height


def parse_row_count(tags, total_length_m):
	"""Originalstrategie: tree_count/trees oder alle 8m, maximal 500."""
	value = str(tags.get("tree_count") or tags.get("trees") or "").strip()
	match = re.match(r"^[+]?\d+", value)
	tagged = int(match.group()) if match is not None else None
	if tagged is not None and tagged > 0:
		return min(MAX_ROW_SAMPLES, tagged), True
	count = round(total_length_m / ROW_SPACING_M)
	return min(MAX_ROW_SAMPLES, max(1, count)), False


def sample_row(row):
	"""Gleiche Endpunkt-/Mittenregel wie im Tile-Builder, nun metrisch in 31256."""
	geometry = row.get("geometry")
	if not isinstance(geometry, list):
		return []
	points = []
	for position in geometry:
		if not isinstance(position, dict):
			return []
		try:
			points.append(metric_point(position.get("lon"), position.get("lat")))
		except ValueError:
			return []
	if len(points) < 2:
		return []
	segments = []
	length = 0.0
	for a, b in zip(points, points[1:]):
		distance = a.distance(b)
		if distance <= 0:
			continue
		segments.append((a, b, length, length + distance))
		length += distance
	if not segments:
		return []
	count, tagged = parse_row_count(row.get("tags") or {}, length)

	def point_at(distance):
		for a, b, start, end in segments:
			if distance <= end:
				fraction = (distance - start) / (end - start)
				return Point(a.x + fraction * (b.x - a.x),
					a.y + fraction * (b.y - a.y))
		return segments[-1][1]

	if count == 1:
		return [point_at(length / 2)]
	if tagged:
		return [point_at(length * i / (count - 1)) for i in range(count)]
	return [point_at(length * (i + 0.5) / count) for i in range(count)]


def city_point_index(wien_features):
	"""Wiener Vorrang gilt auch für Standorte ohne bekannte Kronenklasse."""
	index = PointGrid()
	count = 0
	for feature in wien_features:
		geometry = feature.get("geometry") or {}
		if geometry.get("type") != "Point":
			continue
		coords = geometry.get("coordinates") or []
		if len(coords) < 2:
			continue
		try:
			point = metric_point(coords[0], coords[1])
		except ValueError:
			continue
		props = feature.get("properties") or {}
		identifier = props.get("BAUM_ID") or props.get("OBJECTID") or feature.get("id")
		index.add(point, str(identifier))
		count += 1
	return index, count


def selected_osm_trees(wien_features, osm_document, *, allow_estimates=True):
	"""Wien > OSM tree node > row samples, wie im existierenden Build."""
	if not isinstance(osm_document, dict) or not isinstance(osm_document.get("elements"), list):
		raise ValueError("OSM-Quelle muss rohes Overpass-JSON mit elements sein")
	if osm_document.get("remark"):
		raise ValueError("Overpass hat eine nicht bestätigte oder unvollständige Antwort gemeldet")
	elements = osm_document["elements"]
	if not elements:
		raise ValueError("OSM-Rohdaten sind leer; nicht als vollständige Variante B werten")
	city_index, city_count = city_point_index(wien_features)
	explicit_index = PointGrid()
	row_index = PointGrid()
	seen = set()
	output = []
	counts = Counter()
	rows = []
	nodes = []
	for element in elements:
		if not isinstance(element, dict) or element.get("type") not in ("node", "way"):
			raise ValueError("Ungültiger OSM-Elementtyp")
		ident = element.get("id")
		key = (element["type"], ident)
		if not isinstance(ident, int) or ident <= 0 or key in seen:
			raise ValueError("Doppelte oder ungültige OSM-ID")
		seen.add(key)
		tags = element.get("tags") or {}
		if element["type"] == "node" and tags.get("natural") == "tree":
			nodes.append(element)
		elif element["type"] == "way" and tags.get("natural") == "tree_row":
			rows.append(element)
		else:
			raise ValueError("Nicht als Baum/Baumreihe gekennzeichnetes OSM-Element")
	counts["osm_nodes_geladen"] = len(nodes)
	counts["osm_reihen_geladen"] = len(rows)
	counts["wien_punkte_fuer_dubletten"] = city_count

	def record(point, tags, provider, identifier, *, osm_id, row_index_value=None,
		row_total=None):
		diameter, status, field, height = osm_crown_diameter(tags,
			allow_estimates=allow_estimates)
		if diameter is None:
			counts["osm_kronendurchmesser_fehlend_strikt"] += 1
			return
		output.append({
			"provider": provider, "id": identifier, "point": point,
			"diameter_m": diameter, "diameter_quality": status,
			"diameter_field": field,
			"osm_id": osm_id, "osm_type": "way" if row_index_value is not None else "node",
			"osm_row_index": row_index_value, "osm_row_count": row_total,
			"osm_height_m": height,
		})
		counts[status] += 1

	for el in nodes:
		try:
			p = metric_point(el.get("lon"), el.get("lat"))
		except ValueError:
			counts["osm_nodes_ungueltige_koordinaten"] += 1
			continue
		if city_index.near(p, WFS_OSM_DEDUP_M):
			counts["osm_nodes_dublette_wien"] += 1
			continue
		if explicit_index.near(p, OSM_NODE_DEDUP_M):
			counts["osm_nodes_dublette_osm"] += 1
			continue
		identifier = f"osm:n{el['id']}"
		# wie der Originalbuild: auch Punkte ohne Kronenmaß gelten als
		# explizite Einzelbäume und verdrängen Baumreihen-Samples.
		explicit_index.add(p, identifier)
		counts["osm_nodes_nach_merge"] += 1
		record(p, el.get("tags") or {}, "osm_tree", identifier, osm_id=el["id"])

	for el in rows:
		samples = sample_row(el)
		if not samples:
			counts["osm_reihen_ungueltige_geometrie"] += 1
			continue
		counts["osm_reihen_samples_erzeugt"] += len(samples)
		for i, p in enumerate(samples):
			if city_index.near(p, WFS_OSM_DEDUP_M):
				counts["osm_reihen_dublette_wien"] += 1
				continue
			if explicit_index.near(p, ROW_EXPLICIT_DEDUP_M):
				counts["osm_reihen_dublette_osm_einzelbaum"] += 1
				continue
			if row_index.near(p, ROW_ROW_DEDUP_M):
				counts["osm_reihen_dublette_anderer_reihe"] += 1
				continue
			identifier = f"osm:w{el['id']}:{i}"
			row_index.add(p, identifier)
			counts["osm_reihen_samples_nach_merge"] += 1
			record(p, el.get("tags") or {}, "osm_tree_row", identifier,
				osm_id=el["id"], row_index_value=i, row_total=len(samples))
	counts["osm_baeume_nach_kronenfilter"] = len(output)
	return output, dict(sorted(counts.items()))
