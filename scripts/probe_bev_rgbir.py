#!/usr/bin/env python3
"""Methode D1 – BEV-RGBI-Orthofoto untersuchen, nicht Kronen klassifizieren.

Nimmt lokal vorhandene TIFF/GeoTIFF-Dateien entgegen. Kein Download großer
BEV-50x50-km-Kacheln durch das Skript. Zuerst GDAL-Metadaten zu Bändern,
Lagebezug und Pixelauflösung prüfen; optional denselben kleinen FMZK-Ausschnitt
in metrischem EPSG:31256 extrahieren. Keine automatische Bandzuordnung
(Rot/NIR) und keine NDVI-Schwelle ohne Quellenprüfung.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

from pyproj import CRS, Transformer
from shapely.geometry import Polygon, box

from scripts.fmzk_source import load_polygons

DEFAULT_FMZK = Path("data/processed/fmzk_test.gpkg")
DEFAULT_OUTPUT = Path("data/processed/baumkronen/bev_rgbir")
MAX_SIDE = 4096
MAX_PIXELS = 12_000_000
MAX_INFO_LENGTH = 2_000_000


def gdal_info(source):
	if shutil.which("gdalinfo") is None:
		raise ValueError("gdalinfo fehlt: sudo apt install gdal-bin")
	completed = subprocess.run(
		["gdalinfo", "-json", str(source)],
		capture_output=True, text=True, check=False, timeout=90,
	)
	if completed.returncode != 0:
		raise ValueError(f"gdalinfo fehlgeschlagen: {completed.stderr[:700]}")
	if len(completed.stdout) > MAX_INFO_LENGTH:
		raise ValueError("GDAL-Metadaten ungewöhnlich groß")
	try:
		info = json.loads(completed.stdout)
	except json.JSONDecodeError as exc:
		raise ValueError("gdalinfo lieferte keine gültige JSON-Antwort") from exc
	if not isinstance(info, dict):
		raise ValueError("Ungültiger GDAL-Bericht")
	return info


def inspect_dataset(info, *, source_crs=None):
	"""Strikte Voraussetzungen, keine Annahme über NIR-Bandnummer."""
	size = info.get("size")
	if not (isinstance(size, list) and len(size) == 2
		and all(isinstance(n, int) and n > 0 for n in size)):
		raise ValueError("Raster hat keine gültige Pixelgröße")
	bands = info.get("bands")
	if not isinstance(bands, list) or len(bands) < 4:
		raise ValueError("Für Methode D benötigen wir ein echtes RGBI-Raster mit mindestens vier Bändern; eine 3-Band-CIR-Anzeige genügt nicht")
	transform = info.get("geoTransform")
	if not (isinstance(transform, list) and len(transform) == 6
		and all(isinstance(v, (int, float)) and math.isfinite(v) for v in transform)):
		raise ValueError("GDAL erkennt keine gültige Georeferenzierung: Worldfile/GeoTIFF-Metadaten kontrollieren")
	metadata_wkt = (info.get("coordinateSystem") or {}).get("wkt")
	if metadata_wkt:
		crs = CRS.from_wkt(metadata_wkt)
		if source_crs is not None and crs != CRS.from_user_input(source_crs):
			raise ValueError("Explizite Quellprojektion widerspricht den Rastermetadaten")
	else:
		if source_crs is None:
			raise ValueError("Quellprojektion fehlt (z.B. nur .tfw): --source-crs EPSG:31256 nur nach ausdrücklicher Metadatenkontrolle setzen")
		crs = CRS.from_user_input(source_crs)
	if not crs.is_projected:
		raise ValueError("Quellprojektion ist nicht metrisch/projiziert; vor dem Zuschnitt prüfen")
	gt = transform
	w, h = size
	def point(col, row):
		return (gt[0] + col * gt[1] + row * gt[2],
			gt[3] + col * gt[4] + row * gt[5])
	corners = [point(0, 0), point(w, 0), point(w, h), point(0, h)]
	to_metric = Transformer.from_crs(crs, "EPSG:31256", always_xy=True).transform
	projected = Polygon([to_metric(*p) for p in corners])
	if not projected.is_valid or projected.is_empty or projected.area <= 0:
		raise ValueError("Raster-Footprint ist nicht verwendbar")
	band_list = []
	for i, band in enumerate(bands, 1):
		band_list.append({
			"index": i,
			"color_interpretation": band.get("colorInterpretation"),
			"description": band.get("description"),
			"data_type": band.get("type"),
			"nodata": band.get("noDataValue"),
			"unit": band.get("unit"),
		})
	return {
		"size_px": size,
		"band_count": len(bands),
		"bands": band_list,
		"crs": crs.to_string(),
		"crs_epsg": crs.to_epsg(),
		"source_crs_explicit": not bool(metadata_wkt),
		"geotransform": gt,
		"pixel_size_source_units": [
			math.hypot(gt[1], gt[4]),
			math.hypot(gt[2], gt[5]),
		],
		"footprint_epsg31256_bounds": list(projected.bounds),
	}, projected


def clip_geometry(area, *, padding_m=15.0, pixel_size_m=0.20):
	if not 0 <= padding_m <= 100:
		raise ValueError("Puffer muss zwischen 0 und 100 m liegen")
	if not 0.15 <= pixel_size_m <= 1.0:
		raise ValueError("Anfragepixelgröße muss zwischen 0,15 und 1,0 m liegen")
	x0, y0, x1, y1 = area.bounds
	x0 -= padding_m
	x1 += padding_m
	y0 -= padding_m
	y1 += padding_m
	w = math.ceil((x1-x0) / pixel_size_m)
	h = math.ceil((y1-y0) / pixel_size_m)
	if w > MAX_SIDE or h > MAX_SIDE or w*h > MAX_PIXELS:
		raise ValueError("Testausschnitt zu groß für D1-Diagnose; BBOX/Puffer/Pixelgröße prüfen")
	return [x0, y0, x1, y1], [w, h]


def validate_coverage(footprint, bbox):
	roi = box(*bbox)
	missing = roi.difference(footprint)
	if missing.area > max(0.01, roi.area * 1e-7):
		raise ValueError(f"BEV-Raster deckt den FMZK-Ausschnitt nicht vollständig ab: {missing.area:.2f} m² fehlen. Nachbar-Kacheln ggf. zu einem VRT mosaikieren.")
	return True


def extract_window(source, *, target, bbox, pixel_size_m, source_crs=None):
	if shutil.which("gdalwarp") is None:
		raise ValueError("gdalwarp fehlt: sudo apt install gdal-bin")
	if target.exists():
		raise ValueError(f"Ausgabe existiert bereits: {target}; altes Ergebnis bewusst archivieren/entfernen")
	cmd = [
		"gdalwarp",
		"-q",
		"-of", "GTiff",
		"-t_srs", "EPSG:31256",
		"-te", *(f"{v:.8f}" for v in bbox),
		"-tr", str(pixel_size_m), str(pixel_size_m),
		"-r", "near",
		"-co", "COMPRESS=DEFLATE",
		"-co", "TILED=YES",
		"-co", "BIGTIFF=IF_SAFER",
	]
	if source_crs is not None:
		cmd.extend(["-s_srs", str(source_crs)])
	cmd.extend([str(source), str(target)])
	try:
		result = subprocess.run(cmd, capture_output=True, text=True,
			check=False, timeout=240)
	except subprocess.TimeoutExpired as exc:
		raise ValueError("GDAL-Zuschnitt nach 240 s abgebrochen") from exc
	if result.returncode != 0:
		raise ValueError(f"gdalwarp fehlgeschlagen: {result.stderr[-1000:]}")
	if not target.is_file() or target.stat().st_size <= 0:
		raise ValueError("GDAL hat keine Rasterdatei ausgegeben")
	return cmd


def run(*, source, fmzk=DEFAULT_FMZK, output=DEFAULT_OUTPUT, clip=False,
	source_crs=None, padding_m=15.0, pixel_size_m=0.20,
	acquisition_year=None):
	source = Path(source)
	if not source.is_file():
		raise FileNotFoundError(f"BEV-Raster nicht gefunden: {source}")
	if source.suffix.lower() not in (".tif", ".tiff", ".vrt"):
		raise ValueError("Bitte TIFF/GeoTIFF oder explizit erzeugtes GDAL-VRT übergeben, keine gerenderte PNG/JPEG-WMS-Karte")
	if acquisition_year is not None and not 2010 <= acquisition_year <= 2026:
		raise ValueError("Unplausibles Erhebungsjahr; Metadaten prüfen")
	info = gdal_info(source)
	metadata, footprint = inspect_dataset(info, source_crs=source_crs)
	output = Path(output)
	output.mkdir(parents=True, exist_ok=True)
	report_path = output / "bev_rgbir_diagnose.json"
	report = {
		"schema_version": 1,
		"created_utc": datetime.now(timezone.utc).isoformat(),
		"phase": "D1 – Quellenprüfung/Diagnose, ausdrücklich keine Kronenklassifikation",
		"quelle": str(source),
		"quelle_bytes": source.stat().st_size,
		"quelle_aufnahmejahr_nach_manuel­ler_pruefung": acquisition_year,
		"datensatz": metadata,
		"grafik_kanaele_bestaetigt": False,
		"wichtig": [
			"Vier oder mehr Rasterbänder alleine beweisen keine definierte Rot-/NIR-Bandreihenfolge; vom BEV-Metadatensatz prüfen.",
			"RGBI enthält Nahinfrarot. Eine RGB- oder dreikanalige CIR-Darstellung ist keine gleichwertige NDVI-Quelle.",
			"NDVI (NIR - Rot) / (NIR + Rot) identifiziert Vegetation, nicht zuverlässig die Kronen von Bäumen.",
			"NDVI-Schwellen, Kronenpolygone und Überschirmungsberechnung erfolgen erst nach gesonderter Band-/Höhenmodellprüfung.",
			"Erhebungsjahr nicht aus Produkttitel 'aktuell' oder Downloadjahr abgeleitet.",
		],
	}
	if clip:
		_, fmzk_manifest, area, _ = load_polygons(fmzk)
		bbox, dimensions = clip_geometry(area, padding_m=padding_m,
			pixel_size_m=pixel_size_m)
		validate_coverage(footprint, bbox)
		window = output / "bev_rgbir_testausschnitt.tif"
		command = extract_window(source, target=window, bbox=bbox,
			pixel_size_m=pixel_size_m,
			source_crs=source_crs if metadata["source_crs_explicit"] else None)
		window_info = gdal_info(window)
		window_metadata, _ = inspect_dataset(window_info)
		report["clip"] = {
			"fmzk": str(fmzk),
			"bbox_lon_lat": fmzk_manifest["bbox_lon_lat"],
			"bbox_epsg31256": bbox,
			"target_pixels_approx": dimensions,
			"gdal_command": command,
			"output": str(window),
			"output_bytes": window.stat().st_size,
			"output_sha256": hashlib.sha256(window.read_bytes()).hexdigest()
				if window.stat().st_size <= 150_000_000 else None,
			"result_raster": window_metadata,
			"resampling": "nearest; gerasterte Ausgabegitterzellen dürfen nicht mit unveränderten Originalpixeln gleichgesetzt werden",
		}
	report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
		encoding="utf-8")
	print(f"BEV-RGBI: {metadata['size_px'][0]} × {metadata['size_px'][1]}, {metadata['band_count']} Bänder")
	print(f"CRS: {metadata['crs']}, Pixelgröße in CRS-Einheiten: {metadata['pixel_size_source_units']}")
	for b in metadata["bands"]:
		print(f"  Band {b['index']}: {b['color_interpretation'] or 'unbekannt'}, {b['data_type']}, NoData={b['nodata']}")
	print(f"Diagnose: {report_path}")
	if clip:
		print(f"Testausschnitt: {report['clip']['output']}")
	print("Keine Zuordnung von NIR/Rot, kein NDVI und keine Baumkronenpolygone berechnet.")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--input", type=Path, required=True, help="Lokales BEV RGBI-TIFF oder VRT")
	parser.add_argument("--fmzk", type=Path, default=DEFAULT_FMZK)
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
	parser.add_argument("--clip", action="store_true",
		help="Zusätzlich den metrisch georeferenzierten kleinen FMZK-Testausschnitt extrahieren")
	parser.add_argument("--source-crs", type=str,
		help="Nur nach manueller Kontrolle für TIFF ohne eingebettetes CRS, z.B. EPSG:31256")
	parser.add_argument("--padding-m", type=float, default=15.0)
	parser.add_argument("--pixel-size-m", type=float, default=0.20)
	parser.add_argument("--acquisition-year", type=int,
		help="Tatsächliches Bildflugjahr aus BEV-Metadaten, nicht Downloadjahr")
	args = parser.parse_args()
	try:
		run(source=args.input, fmzk=args.fmzk, output=args.out_dir, clip=args.clip,
			source_crs=args.source_crs, padding_m=args.padding_m,
			pixel_size_m=args.pixel_size_m,
			acquisition_year=args.acquisition_year)
	except (OSError, ValueError, TypeError, KeyError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
