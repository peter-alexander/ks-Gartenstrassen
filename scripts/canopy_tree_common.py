"""Gemeinsame Geometrie- und Attributhelfer für getrennte Kronenprovider A und B.

Wird von beiden implementierenden Modulen verwendet. Enthält keine
Straßenraum-Zuordnung, keinen Download und keine Quellenkombination.
"""

from collections import Counter
import hashlib
import json
import math
import re
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Point

from scripts.geojson_crs import require_geojson_lonlat

# KRONENDURCHMESSER ist nur der Wiener Kategoriencode;
# KRONENDURCHMESSER_TXT enthält die metrischen Klassenintervalle.
CITY_DIAMETER_FIELD = "KRONENDURCHMESSER_TXT"
CITY_CATEGORY_FIELD = "KRONENDURCHMESSER"
OSM_DIAMETER_FIELDS = ("diameter_crown", "crown_diameter")
CROWN_RANGE = re.compile(
	r"^\s*(\d+(?:[.,]\d+)?)\s*[-–—]\s*(\d+(?:[.,]\d+)?)\s*m\s*$",
	re.IGNORECASE,
)
MAX_DIAMETER_M = 50
DUPLICATE_DISTANCE_M = 2.0


def read_points(source, *, provider):
	path = Path(source)
	if not path.is_file():
		raise FileNotFoundError(f"Baumquell-Datei fehlt: {path}")
	data = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
		raise ValueError(f"{provider}: GeoJSON-FeatureCollection erwartet")
	require_geojson_lonlat(data, label=provider)
	if not isinstance(data.get("features"), list):
		raise ValueError(f"{provider}: features fehlen")
	return data["features"], hashlib.sha256(path.read_bytes()).hexdigest()


def parse_wien_crown_range(value):
	"""Liest nur explizite geschlossene Meterintervalle, z. B. '16-18 m'.

	Die Daten sind kategorisiert, nicht metergenau. Der Intervallmittelpunkt
	ist daher eine methodisch deklarierte Näherung, kein Messwert.
	"""
	if value is None or not str(value).strip():
		return None, "durchmesser_fehlt"
	text = str(value).replace(chr(160), " ").strip()
	match = CROWN_RANGE.fullmatch(text)
	if match is None:
		return None, "unlesbare_oder_offene_kronenklasse"
	lower, upper = (float(group.replace(",", ".")) for group in match.groups())
	if not (0 <= lower < upper <= MAX_DIAMETER_M):
		return None, "unplausible_kronenklasse"
	midpoint = (lower + upper) / 2
	if midpoint <= 0:
		return None, "unplausible_kronenklasse"
	return (lower, upper, midpoint), "klassenmittelwert"


def diameter_from_properties(properties, provider, *, default_osm_diameter=None):
	if provider == "wien":
		# Niemals auf das numerische KRONENDURCHMESSER-Feld zurückfallen:
		# Das ist nur ein Kategoriecode, keine Längenangabe.
		interval, status = parse_wien_crown_range(properties.get(CITY_DIAMETER_FIELD))
		if interval is None:
			return None, status, CITY_DIAMETER_FIELD
		return interval[2], status, CITY_DIAMETER_FIELD
	fields = OSM_DIAMETER_FIELDS
	for field in fields:
		if field not in properties or properties[field] is None or str(properties[field]).strip() == "":
			continue
		value = properties[field]
		try:
			diameter = float(value)
		except (TypeError, ValueError):
			return None, "unlesbarer_durchmesser", field
		if not math.isfinite(diameter) or not (0 < diameter <= MAX_DIAMETER_M):
			return None, "unplausibler_durchmesser", field
		return diameter, "gemessen_oder_erfasst", field
	if provider == "osm" and default_osm_diameter is not None:
		if not math.isfinite(default_osm_diameter) or not (0 < default_osm_diameter <= MAX_DIAMETER_M):
			raise ValueError("OSM-Standarddurchmesser muss größer 0 und höchstens 50 m sein")
		return default_osm_diameter, "explizit_geschaetzt", "osm_default"
	return None, "durchmesser_fehlt", None


def parse_trees(features, provider, *, default_osm_diameter=None):
	to_m = Transformer.from_crs("EPSG:4326", "EPSG:31256", always_xy=True).transform
	trees = []
	reasons = Counter()
	seen = set()
	for index, feature in enumerate(features):
		if not isinstance(feature, dict) or feature.get("type") != "Feature":
			reasons["ungueltiges_feature"] += 1
			continue
		geometry = feature.get("geometry") or {}
		properties = feature.get("properties") or {}
		if not isinstance(properties, dict):
			reasons["ungueltige_attribute"] += 1
			continue
		if provider == "osm" and properties.get("natural") == "tree_row":
			reasons["baumreihe_ohne_einzelbaumgeometrie"] += 1
			continue
		if provider == "osm" and properties.get("natural") != "tree":
			# Aus OSM-Exports ausschließlich bestätigte Baum-Punkte
			# akzeptieren, nicht beliebige Punkte ohne natural-Tag.
			reasons["kein_osm_baum"] += 1
			continue
		if geometry.get("type") != "Point":
			reasons["keine_punktgeometrie"] += 1
			continue
		coords = geometry.get("coordinates") or []
		if len(coords) < 2:
			reasons["ungueltige_koordinate"] += 1
			continue
		lon, lat = coords[:2]
		if not (isinstance(lon, (int, float)) and isinstance(lat, (int, float))
			and math.isfinite(lon) and math.isfinite(lat)
			and -180 <= lon <= 180 and -90 <= lat <= 90):
			reasons["ungueltige_koordinate"] += 1
			continue
		diameter, quality, field = diameter_from_properties(properties, provider,
			default_osm_diameter=default_osm_diameter)
		if diameter is None:
			reasons[quality] += 1
			continue
		identifier = str(feature.get("id") or properties.get("OBJECTID")
			or properties.get("objectid") or properties.get("id") or f"index:{index}")
		key = (provider, identifier)
		if key in seen:
			reasons["doppelte_quell_id"] += 1
			continue
		seen.add(key)
		x, y = to_m(lon, lat)
		trees.append({
			"provider": provider, "id": identifier, "point": Point(x, y),
			"diameter_m": diameter, "diameter_quality": quality,
			"diameter_field": field,
			"diameter_class_raw": (
				str(properties.get(CITY_DIAMETER_FIELD))
				if provider == "wien" else None
			),
			"diameter_category_code": (
				properties.get(CITY_CATEGORY_FIELD) if provider == "wien" else None
			),
		})
	return trees, dict(sorted(reasons.items()))


def merge_trees(city, osm, *, duplicate_distance=DUPLICATE_DISTANCE_M):
	"""Städtische Punkte behalten; nahe OSM-Punkte vorsichtig als mögliche Dublette.

	Kein globales Vereinigen benachbarter Bäume untereinander. Prüfbare Liste
	mit möglicher Fehlzuordnung im Bericht; OSM-Punkt zählt nicht doppelt.
	"""
	if not (0 <= duplicate_distance <= 5):
		raise ValueError("Dublettenabstand muss zwischen 0 und 5 Metern liegen")
	combined = list(city)
	matches = []
	for tree in osm:
		nearest = min(city, key=lambda other: tree["point"].distance(other["point"]), default=None)
		distance = tree["point"].distance(nearest["point"]) if nearest is not None else math.inf
		if nearest is not None and distance <= duplicate_distance:
			matches.append({
				"osm_id": tree["id"], "wien_id": nearest["id"],
				"abstand_m": round(distance, 3),
				"status": "potenzielle_dublette_ausgeschlossen_pruefen",
			})
		else:
			combined.append(tree)
	return combined, matches


def crowns_from_trees(trees, *, area_of_interest, max_radius_m=25):
	"""Erzeuge Kronenkreise vollflächig, auch bei Baumstandorten außerhalb der Straße."""
	if not trees:
		raise ValueError("Keine verwendbaren Baumstandorte")
	crowns = []
	skipped = Counter()
	features = []
	to_lonlat = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform
	# clippen erst im Messmodul; Bäume außerhalb können in die Straße ragen.
	for tree in trees:
		if tree["point"].distance(area_of_interest) > max_radius_m:
			skipped["ausserhalb_untersuchungsbereich"] += 1
			continue
		radius = tree["diameter_m"] / 2
		if radius > max_radius_m:
			raise ValueError("Kronenradius über max_radius_m")
		circle = tree["point"].buffer(radius, quad_segs=32)
		if not circle.intersects(area_of_interest):
			skipped["krone_ohne_kontakt_zum_gebiet"] += 1
			continue
		crowns.append(circle)
		center = to_lonlat(tree["point"].x, tree["point"].y)
		geometry = {
			"type": "Polygon",
			"coordinates": [[list(to_lonlat(x, y)) for x, y in circle.exterior.coords]],
		}
		features.append({"type": "Feature", "properties": {
			"source": tree["provider"], "source_id": tree["id"],
			"crown_diameter_m": tree["diameter_m"],
			"diameter_status": tree["diameter_quality"],
			"diameter_feld": tree["diameter_field"],
			"diameter_klasse_text": tree.get("diameter_class_raw"),
			"diameter_kategorie": tree.get("diameter_category_code"),
			"center_lon": center[0], "center_lat": center[1],
			"geometry_method": "point_buffer_circle_32",
		}, "geometry": geometry})
	return features, dict(sorted(skipped.items()))
