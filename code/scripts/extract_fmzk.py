#!/usr/bin/env python3
"""Lokalen FMZK-Ausschnitt als GeoPackage extrahieren (ohne WFS)."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
from urllib.parse import quote

from pyproj import Transformer
from shapely.geometry import Polygon

LAYER = "FMZK_WIEN_20260112"
DEFAULT_BBOX = "16.361012,48.221226,16.366948,48.224902"
DEFAULT_OUTPUT = Path("data/processed/fmzk_test.gpkg")
SOURCE_CANDIDATES = (
	Path("data/FMZK_WIEN_GP.gpkg"),
	Path("data/raw/FMZK_WIEN_GP.gpkg"),
	Path("FMZK_WIEN_GP.gpkg"),
)


def parse_bbox(text):
	try:
		coords = tuple(float(s.strip()) for s in text.split(","))
		if len(coords) != 4:
			raise ValueError()
	except ValueError as exc:
		raise ValueError("BBOX: west,süd,ost,nord in EPSG:4326 erwartet") from exc
	west, south, east, north = coords
	if not (16.0 < west < east < 17.0 and 48.0 < south < north < 49.0):
		raise ValueError("BBOX muss ein gültiger kleiner Wiener Ausschnitt sein")
	if (east - west) * (north - south) > 0.0002:
		raise ValueError("BBOX für den Prototyp zu groß; bitte kleineren Ausschnitt wählen")
	return coords


def find_source(explicit=None):
	if explicit is not None:
		path = Path(explicit)
		if not path.is_file():
			raise FileNotFoundError(f"GeoPackage nicht gefunden: {path}")
		return path
	for path in SOURCE_CANDIDATES:
		if path.is_file():
			return path
	raise FileNotFoundError("FMZK_WIEN_GP.gpkg nicht gefunden; mit --source /pfad/zur/Datei.gpkg angeben")


def gpkg_info(path, layer):
	# Verhindert, dass sqlite3 bei falschem Pfad stillschweigend eine Datei anlegt.
	uri = "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro"
	with sqlite3.connect(uri, uri=True) as conn:
		row = conn.execute(
			"SELECT c.table_name, c.srs_id, g.column_name, g.srs_id "
			"FROM gpkg_contents c JOIN gpkg_geometry_columns g "
			"ON c.table_name=g.table_name WHERE c.table_name=?",
			(layer,),
		).fetchone()
		if not row:
			raise ValueError(f"GPKG-Layer {layer!r} nicht gefunden")
		_, content_srs, geometry_column, geometry_srs = row
		if content_srs != 31256 or geometry_srs != 31256:
			raise ValueError(f"{layer}: EPSG:31256 erwartet; gefunden {content_srs}/{geometry_srs}")
		cols = {row[1] for row in conn.execute(f'PRAGMA table_info("{layer}")')}
		for required in ("F_KLASSE", "F_KLASSE_TEXT", "FMZK_ID"):
			if required not in cols:
				raise ValueError(f"{layer}: Attribut {required} fehlt")
		rtree = f"rtree_{layer}_{geometry_column}"
		has_rtree = conn.execute(
			"SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (rtree,)
		).fetchone() is not None
	return {"geometry_column": geometry_column, "rtree_present": has_rtree}


def projected_clip(bbox, segments=16):
	"""Geografisches Rechteck entlang der Kanten verdichten und nach 31256 projizieren."""
	west, south, east, north = bbox
	corners = [(west, south), (east, south), (east, north), (west, north)]
	points = []
	for i in range(4):
		start, end = corners[i], corners[(i + 1) % 4]
		for j in range(segments):
			fraction = j / segments
			points.append((start[0] + (end[0] - start[0]) * fraction,
				start[1] + (end[1] - start[1]) * fraction))
	project = Transformer.from_crs("EPSG:4326", "EPSG:31256", always_xy=True)
	polygon = Polygon([project.transform(*point) for point in points])
	if not polygon.is_valid or polygon.area <= 0:
		raise ValueError("Ungültiges projiziertes Zuschnittpolygon")
	return polygon


def build_commands(source, candidates_path, clipped_path, polygon, make_valid=False):
	# Erste Stufe: räumlicher Index + Umwandlung der Kurven in lineare Polygone.
	# Zweite Stufe: exakter Zuschnitt an der projizierten (verdichteten) WGS84-BBOX.
	minx, miny, maxx, maxy = polygon.bounds
	first = [
		"ogr2ogr", "-f", "GPKG", str(candidates_path), str(source), LAYER,
		"-spat", *(str(value) for value in (minx - 1, miny - 1, maxx + 1, maxy + 1)),
		"-nlt", "CONVERT_TO_LINEAR", "-preserve_fid",
		"-nln", "fmzk_candidates", "-lco", "SPATIAL_INDEX=NO", "-lco", "FID=id",
	]
	if make_valid:
		first.append("-makevalid")
	second = [
		"ogr2ogr", "-f", "GPKG", str(clipped_path), str(candidates_path),
		"fmzk_candidates", "-clipsrc", polygon.wkt, "-nln", "fmzk",
		"-nlt", "PROMOTE_TO_MULTI", "-preserve_fid",
		"-lco", "SPATIAL_INDEX=YES", "-lco", "FID=id",
	]
	return first, second


def extract(source, output, bbox, *, overwrite=False, make_valid=False):
	source, output = Path(source).resolve(), Path(output).resolve()
	if source == output:
		raise ValueError("Quell- und Zieldatei dürfen nicht identisch sein")
	if output.exists() and not overwrite:
		raise FileExistsError(f"Ziel existiert: {output} (erneut mit --overwrite ausführen)")
	if shutil.which("ogr2ogr") is None:
		raise RuntimeError("ogr2ogr fehlt. Unter Ubuntu: sudo apt install gdal-bin")
	meta = gpkg_info(source, LAYER)
	if not meta["rtree_present"]:
		print("Warnung: GPKG besitzt keinen erkannten RTree; räumlicher Abruf könnte langsam sein")
	polygon = projected_clip(bbox)
	output.parent.mkdir(parents=True, exist_ok=True)
	with tempfile.TemporaryDirectory(prefix=".fmzk_extract_", dir=output.parent) as tmp:
		temp_path = Path(tmp)
		candidates_path = temp_path / "candidates.gpkg"
		clipped_path = temp_path / "clipped.gpkg"
		for index, command in enumerate(build_commands(source, candidates_path, clipped_path, polygon, make_valid), 1):
			print(f"Schritt {index}/2: {'räumlich filtern und Kurven linearisieren' if index == 1 else 'auf BBOX zuschneiden'}", flush=True)
			subprocess.run(command, check=True)
		result = gpkg_info(clipped_path, "fmzk")
		if result["geometry_column"] == "":
			raise ValueError("Die Ergebnisgeometrie fehlt")
		uri = "file:" + quote(str(clipped_path.resolve()), safe="/") + "?mode=ro"
		with sqlite3.connect(uri, uri=True) as conn:
			count = conn.execute('SELECT COUNT(*) FROM "fmzk"').fetchone()[0]
		if count == 0:
			raise ValueError("Keine Features im Ausschnitt")
		# Quell-GPKG bleibt unter allen Umständen unangetastet.
		clipped_path.replace(output)
	report = {
		"source_file": str(source),
		"source_size_bytes": source.stat().st_size,
		"source_modified_utc": datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).isoformat(),
		"source_layer": LAYER,
		"output_layer": "fmzk",
		"output_srs": "EPSG:31256",
		"bbox_lon_lat": list(bbox),
		"feature_count": count,
		"source_rtree_present": meta["rtree_present"],
		"make_valid_requested": make_valid,
		"generated_at_utc": datetime.now(timezone.utc).isoformat(),
		"note": "Geometrien wurden linearisiert und auf die geografische Test-BBOX zugeschnitten; dies sind alle FMZK-Klassen, nicht nur Straßenflächen.",
	}
	report_path = output.with_suffix(".json")
	report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	print(f"Ergebnis: {output} – {count} Features in EPSG:31256")
	print(f"Metadaten: {report_path}")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--source", type=Path, help="Lokale FMZK_WIEN_GP.gpkg (sonst automatische Suche)")
	parser.add_argument("--bbox", default=DEFAULT_BBOX, help="west,süd,ost,nord in EPSG:4326")
	parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
	parser.add_argument("--overwrite", action="store_true", help="Existierende Ausgabe ersetzen (Original bleibt unverändert)")
	parser.add_argument("--make-valid", action="store_true", help="Geometrien vor Zuschnitt reparieren, falls die Originaldaten ungültige Polygone enthalten")
	args = parser.parse_args()
	try:
		source = find_source(args.source)
		extract(source, args.output, parse_bbox(args.bbox),
			overwrite=args.overwrite, make_valid=args.make_valid)
	except (ValueError, OSError, RuntimeError, sqlite3.Error, subprocess.CalledProcessError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
