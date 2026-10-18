"""Fixes metrisches Wienraster (EPSG:31256); keine erfundene Bezirksgrenze.

Tiles sind *Analysekerne*, Puffer dienen nur dem Quellenabruf.
Außenrand/Teilflächen werden für die Flächenbilanz exakt beschnitten.
Der Nutzer stellt für Wien/Bezirk ein echtes AOI-GeoJSON bereit.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Polygon, MultiPolygon, box, shape
from shapely.ops import transform

TO_METRIC = Transformer.from_crs("EPSG:4326", "EPSG:31256",
	always_xy=True).transform
GRID_VERSION = 1
DEFAULT_SIZE = 1000
DEFAULT_HALO = 75


def checksum(path):
	digest = hashlib.sha256()
	with Path(path).open("rb") as src:
		for chunk in iter(lambda: src.read(1024 * 1024), b""):
			digest.update(chunk)
	return digest.hexdigest()


def load_aoi(path):
	"""GeoJSON Polygon/Feature/FeatureCollection – ausdrücklich WGS84."""
	doc = json.loads(Path(path).read_text(encoding="utf-8"))
	if "crs" in doc:
		raise ValueError("AOI muss GeoJSON EPSG:4326 ohne altes crs-Feld sein")
	if doc.get("type") == "FeatureCollection":
		items = doc.get("features", [])
		if not items:
			raise ValueError("AOI ist leer")
		from shapely import union_all
		geoms = [shape(x["geometry"]) for x in items]
		aoi = union_all(geoms)
	elif doc.get("type") == "Feature":
		aoi = shape(doc["geometry"])
	else:
		aoi = shape(doc)
	if not isinstance(aoi, (Polygon, MultiPolygon)) or (
		aoi.is_empty or not aoi.is_valid or aoi.area <= 0):
		raise ValueError("AOI benötigt gültiges Polygon/MultiPolygon")
	lon0, lat0, lon1, lat1 = aoi.bounds
	if not (15.5 < lon0 < lon1 < 17.5 and 47.5 < lat0 < lat1 < 49):
		raise ValueError("AOI außerhalb des zulässigen Wiener Prüfraums")
	projected = transform(TO_METRIC, aoi)
	if not projected.is_valid or projected.is_empty:
		raise ValueError("AOI in EPSG:31256 ungültig")
	return projected


def tile_bounds(ix, iy, size):
	return (ix * size, iy * size, (ix + 1) * size, (iy + 1) * size)


def tile_id(ix, iy):
	# Vorzeichen sind auch in Pfadnamen unterscheidbar.
	return f"x{ix:+07d}_y{iy:+07d}"


def plan(aoi, *, size=DEFAULT_SIZE, halo=DEFAULT_HALO):
	if not isinstance(size, int) or isinstance(size, bool) or not 250 <= size <= 5000:
		raise ValueError("Kachelgröße muss 250–5000 ganze Meter betragen")
	if not isinstance(halo, int) or isinstance(halo, bool) or not 40 <= halo <= 500:
		raise ValueError("Halo muss 40–500 ganze Meter betragen")
	# Bei 5-m-Stützpunkten + max. 25 m Achsdistanz ist
	# 40 m konservativ größer als die erforderliche Suchweite.
	if halo < 25 + 5 + 7:
		raise ValueError("Halo kleiner als Achsdistanz + Abtastung + Knotenradius")
	minx, miny, maxx, maxy = aoi.bounds
	tiles = []
	for ix in range(math.floor(minx/size), math.ceil(maxx/size)):
		for iy in range(math.floor(miny/size), math.ceil(maxy/size)):
			bounds = tile_bounds(ix, iy, size)
			region = box(*bounds).intersection(aoi)
			if region.is_empty or region.area <= 0:
				continue
			tiles.append({
				"id": tile_id(ix, iy),
				"ix": ix, "iy": iy,
				"bounds_31256": list(bounds),
				"aoi_core_m2": region.area,
			})
	tiles.sort(key=lambda tile: (tile["iy"], tile["ix"]))
	if not tiles:
		raise ValueError("AOI enthält keine Kacheln")
	from shapely import union_all
	union = union_all([
		box(*cell["bounds_31256"]).intersection(aoi) for cell in tiles
	])
	if aoi.symmetric_difference(union).area > max(.001, aoi.area*1e-9):
		raise ValueError("Kachelgitter deckt AOI nicht vollständig")
	return tiles


def build_manifest(aoi_path, *, size=DEFAULT_SIZE, halo=DEFAULT_HALO):
	aoi = load_aoi(aoi_path)
	tiles = plan(aoi, size=size, halo=halo)
	return {
		"schema_version": GRID_VERSION,
		"created_utc": datetime.now(timezone.utc).isoformat(),
		"crs": "EPSG:31256",
		"aoi_geojson": str(aoi_path),
		"aoi_sha256": checksum(aoi_path),
		"aoi_area_m2": aoi.area,
		"tile_size_m": size, "halo_m": halo,
		"tiles": tiles,
		"status": "PLAN – keine Aussage über vollständige Geodaten",
	}


def read_manifest(path):
	data = json.loads(Path(path).read_text(encoding="utf-8"))
	if data.get("schema_version") != GRID_VERSION or data.get("crs") != "EPSG:31256":
		raise ValueError("Unbekanntes Wienraster-Manifest")
	# Beim Kopieren eines vollständigen Arbeitsverzeichnisses kann der im
	# Manifest gespeicherte absolute AOI-Pfad auf das alte Laufwerk zeigen.
	# Das Manifest selbst darf nicht geändert werden: sein SHA-256 ist in
	# Straßenraum, Partition und GRM als Herkunftsnachweis hinterlegt.
	# Eine lokale Kopie wird nur bei identischem SHA-256 verwendet.
	local_aoi = Path(path).parent / "aoi.geojson"
	recorded_aoi = Path(data["aoi_geojson"])
	aoi_path = None
	for candidate in dict.fromkeys((local_aoi, recorded_aoi)):
		if candidate.is_file() and checksum(candidate) == data["aoi_sha256"]:
			aoi_path = candidate
			break
	if aoi_path is None:
		raise ValueError("AOI-Datei seit Manifest-Erstellung verändert oder fehlt")
	aoi = load_aoi(aoi_path)
	expected = plan(aoi, size=data["tile_size_m"], halo=data["halo_m"])
	if len(expected) != len(data.get("tiles", [])) or any(
		a["id"] != b.get("id") or a["bounds_31256"] != b.get("bounds_31256")
		for a, b in zip(expected, data["tiles"])):
		raise ValueError("Kachelmanifest weicht von AOI und Parametern ab")
	return data, aoi


def write_manifest(output, data):
	dest = Path(output)
	if dest.exists():
		raise FileExistsError(f"Rastermanifest existiert bereits: {dest}")
	dest.parent.mkdir(parents=True, exist_ok=True)
	dest.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n",
		encoding="utf-8")
	return dest


def main():
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("--aoi", type=Path, required=True,
		help="Echte Wien-/Bezirks-/Testgebietsfläche als WGS84-GeoJSON")
	p.add_argument("--tile-m", type=int, default=DEFAULT_SIZE)
	p.add_argument("--halo-m", type=int, default=DEFAULT_HALO)
	p.add_argument("--out", type=Path, required=True)
	args = p.parse_args()
	try:
		manifest = build_manifest(args.aoi, size=args.tile_m,
			halo=args.halo_m)
		write_manifest(args.out, manifest)
		print(f"Wienraster: {len(manifest['tiles'])} Kacheln, "
			f"{manifest['aoi_area_m2']/1e6:.2f} km² (AOI)")
		print(f"Manifest: {args.out}")
	except (OSError, ValueError, KeyError, TypeError) as exc:
		p.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
