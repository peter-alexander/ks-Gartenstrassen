#!/usr/bin/env python3
"""Austauschbare Baumkronen-Kreise aus Wiener Baumkataster/OSM-GeoJSON.

Die Ausgabe ist ein reines Polygon-GeoJSON in EPSG:4326 für Modul 4.
OSM ohne Kronendurchmesser bleibt ausgeschlossen, außer eine explizite
Schätzung wurde über --osm-default-diameter-m angefordert.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Point, mapping

from scripts.fmzk_source import load_polygons
from scripts.geojson_crs import require_geojson_lonlat

DEFAULT_FMZK = Path("data/processed/fmzk_test.gpkg")
DEFAULT_OUTPUT = Path("data/processed/baumkronen")
CITY_DIAMETER_FIELDS = ("KRONENDURCHMESSER",)
OSM_DIAMETER_FIELDS = ("diameter_crown", "crown_diameter")
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


def diameter_from_properties(properties, provider, *, default_osm_diameter=None):
	fields = CITY_DIAMETER_FIELDS if provider == "wien" else OSM_DIAMETER_FIELDS
	for field in fields:
		if field not in properties or properties[field] is None or str(properties[field]).strip() == "":
			continue
		value = properties[field]
		try:
			# Keine Texte wie "10-15m" oder "ca. 7m" stillschweigend parsen.
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
			"center_lon": center[0], "center_lat": center[1],
			"geometry_method": "point_buffer_circle_32",
		}, "geometry": geometry})
	return features, dict(sorted(skipped.items()))


def run(*, wien, osm=None, fmzk=DEFAULT_FMZK, output=DEFAULT_OUTPUT,
	osm_default_diameter=None, duplicate_distance=DUPLICATE_DISTANCE_M):
	_, manifest, area, _ = load_polygons(fmzk)
	if not wien and not osm:
		raise ValueError("Mindestens eine Quelldatei --wien oder --osm angeben")
	trees = {}
	sources = {}
	exclusions = {}
	for provider, path in (("wien", wien), ("osm", osm)):
		if path is None:
			trees[provider] = []
			continue
		points, digest = read_points(path, provider=provider)
		parsed, excluded = parse_trees(points, provider,
			default_osm_diameter=osm_default_diameter)
		trees[provider] = parsed
		sources[provider] = {"path": str(path), "sha256": digest,
			"eingabe_features": len(points), "verwertbare_baeume": len(parsed)}
		exclusions[provider] = excluded
	merged, matches = merge_trees(trees["wien"], trees["osm"],
		duplicate_distance=duplicate_distance)
	features, spatial_exclusions = crowns_from_trees(merged, area_of_interest=area)
	if not features:
		raise ValueError("Keine Baumkronen überschneiden das Testgebiet; Quellen/BBOX prüfen")
	output = Path(output)
	output.mkdir(parents=True, exist_ok=True)
	geojson_path = output / "baumkronen_kreise.geojson"
	geojson_path.write_text(json.dumps({
		"type": "FeatureCollection", "features": features,
	}, ensure_ascii=False) + "\n", encoding="utf-8")
	report = {
		"schema_version": 1,
		"methode": "Kreis um Baumstandort, Radius halber Kronendurchmesser",
		"status": "Vergleichsvariante, keine vermessenen Kronenpolygone",
		"datum_utc": datetime.now(timezone.utc).isoformat(),
		"fmzk_bbox_lon_lat": manifest["bbox_lon_lat"],
		"quellen": sources, "ausgeschlossene_eingabefeatures": exclusions,
		"baumkronen": len(features),
		"quellen_im_ergebnis": dict(Counter(f["properties"]["source"] for f in features)),
		"ausgeschlossen_raeumlich": spatial_exclusions,
		"osm_default_diameter_m": osm_default_diameter,
		"osm_wien_dublettenabstand_m": duplicate_distance,
		"moegliche_dubletten": matches,
		"bemerkung": "Stammpunkt plus Kreis ist eine Näherung. OSM ohne Kronenmaß ausgeschlossen, sofern Schätzung nicht ausdrücklich aktiviert. Baumreihen separat prüfen.",
		"ausgabe": str(geojson_path),
	}
	(output / "baumkronen_kreise_bericht.json").write_text(
		json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	print(f"Erzeugte Baumkronen-Kreise: {len(features)}")
	print(f"Mögliche OSM/Wien-Dubletten: {len(matches)}")
	print(f"GeoJSON: {geojson_path}")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--wien", type=Path, help="Wiener Baumkataster WFS-GeoJSON")
	parser.add_argument("--osm", type=Path, help="OSM-Baumstandorte als GeoJSON")
	parser.add_argument("--fmzk", type=Path, default=DEFAULT_FMZK)
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
	parser.add_argument("--osm-default-diameter-m", type=float,
		help="Nur für ausdrücklich gewünschte OSM-Schätzvariante, sonst fehlende Durchmesser ausschließen")
	parser.add_argument("--duplicate-distance-m", type=float, default=DUPLICATE_DISTANCE_M)
	args = parser.parse_args()
	try:
		run(wien=args.wien, osm=args.osm, fmzk=args.fmzk, output=args.out_dir,
			osm_default_diameter=args.osm_default_diameter_m,
			duplicate_distance=args.duplicate_distance_m)
	except (OSError, ValueError, KeyError, TypeError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
