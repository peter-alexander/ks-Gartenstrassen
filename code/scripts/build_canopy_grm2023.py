#!/usr/bin/env python3
"""GRM2023-WMS-Baumschicht als austauschbare Kronen-GeoJSON-Maske exportieren.

Für die nachweislich neunfarbige, deckende GetMap-Darstellung ist in der
Legende Baumschicht (Klasse 3) dunkelgrün. WMS-Pixelfarbe #38A800.
Unbekannte Farben, geänderte Quelldaten oder unpassende Georeferenzierung
führen zu einem Abbruch: KEIN stilles Raten, keine unscharfe Farbtoleranz.

Geometrie: exakte Vereinigungsfläche aller WMS-Baumschicht-Pixelzellen
im Anfragegitter; metrisch EPSG:31256; GeoJSON-Ausgabe EPSG:4326.
Die WMS-GetMap-Pixel sind gerendert und nicht zwingend Roh-Rasterzellen.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path

from PIL import Image
from pyproj import CRS, Transformer
from shapely import union_all
from shapely.geometry import Polygon, MultiPolygon, box, mapping
from shapely.ops import transform

DEFAULT_SOURCE = Path("data/processed/baumkronen/grm2023")
DEFAULT_OUTPUT = Path("data/processed/baumkronen/grm2023/processed")
CRS_METRIC = "EPSG:31256"
TREE_RGB = (56, 168, 0)
# Im tatsächlichen GRM2023-WMS-Bild exakt vertretene Kategorien,
# abgeglichen mit der Legende des hochgeladenen Testausschnitts.
CATEGORIES = {
	(211, 255, 190): "Grasschicht",
	(76, 230, 0): "Strauchschicht",
	TREE_RGB: "Baumschicht",
	(215, 176, 158): "nichtversiegelte_flaeche_ohne_acker",
	(235, 235, 235): "versiegelte_flaeche",
	(200, 200, 200): "bebaute_flaeche",
	(255, 255, 190): "ackerflaeche",
	(199, 215, 158): "gruen_auf_ueber_bebauter_flaeche",
	(122, 182, 245): "wasserflaeche",
}
MAX_PIXELS = 3_000_000
MAX_SIDE = 2048


def file_sha256(path):
	return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_source(diagnostic, source, *, require_legend=True):
	"""Versperrt den Export bei nicht zuordenbarer oder veränderter WMS-Bildbasis."""
	if diagnostic.get("schema_version") != 1:
		raise ValueError("Unbekannte Diagnose-Schema-Version")
	wms = diagnostic.get("wms") or {}
	alignment = diagnostic.get("raster_ausrichtung") or {}
	if wms.get("layer") != "GRM2023OGD":
		raise ValueError("Diagnose ist nicht vom GRM2023OGD-Layer")
	if alignment.get("crs") != CRS_METRIC:
		raise ValueError("Nur EPSG:31256 ist als georeferenzierte Rasterbasis geprüft")
	if diagnostic.get("bekannte_fachklasse", {}).get("wert") != 3:
		raise ValueError("Diagnose bestätigt Fachklasse 3 nicht")
	bbox = alignment.get("bbox")
	w, h = alignment.get("width"), alignment.get("height")
	if not (isinstance(bbox, list) and len(bbox) == 4
		and all(isinstance(x, (float, int)) and math.isfinite(x) for x in bbox)
		and bbox[0] < bbox[2] and bbox[1] < bbox[3]
		and isinstance(w, int) and isinstance(h, int)
		and 1 <= w <= MAX_SIDE and 1 <= h <= MAX_SIDE
		and w * h <= MAX_PIXELS):
		raise ValueError("Ungültige Raster-BBOX/Größe im Diagnosebericht")
	raster_path = source / "grm2023_testausschnitt.png"
	if file_sha256(raster_path) != wms.get("getmap_sha256"):
		raise ValueError("WMS-PNG hat einen anderen SHA-256 als in der Diagnose")
	legend = source / "grm2023_legende.png"
	if require_legend:
		if not legend.is_file():
			raise ValueError("WMS-Legende fehlt; Klassenzuordnung ohne Legendenkontrolle nicht ausführen")
		if file_sha256(legend) != wms.get("legende_sha256"):
			raise ValueError("WMS-Legende stimmt nicht mit dem Diagnosebericht überein")
	prj = source / "grm2023_testausschnitt.prj"
	if CRS.from_wkt(prj.read_text(encoding="utf-8")).to_epsg() != 31256:
		raise ValueError("Die Projektionsdatei stimmt nicht mit EPSG:31256 überein")
	pgw = source / "grm2023_testausschnitt.pgw"
	values = [float(line.strip()) for line in pgw.read_text(encoding="ascii").splitlines()
		if line.strip()]
	if len(values) != 6 or not all(math.isfinite(v) for v in values):
		raise ValueError("Ungültiges Worldfile, sechs numerische Zeilen erwartet")
	dx, ry, rx, dy, origin_x, origin_y = values
	expected_dx = (bbox[2] - bbox[0]) / w
	expected_dy = -(bbox[3] - bbox[1]) / h
	# Ohne Rotationsanteile: nur exakt zu unserem 31256-GetMap-Gitter passende Bilder.
	if not (
		math.isclose(dx, expected_dx, abs_tol=1e-9)
		and math.isclose(dy, expected_dy, abs_tol=1e-9)
		and abs(rx) < 1e-12 and abs(ry) < 1e-12
		and math.isclose(origin_x, bbox[0] + expected_dx / 2, abs_tol=1e-8)
		and math.isclose(origin_y, bbox[3] + expected_dy / 2, abs_tol=1e-8)
	):
		raise ValueError("Worldfile passt nicht zu BBOX/Pixelgröße des WMS-Diagnoseberichts")
	return raster_path, bbox, w, h, expected_dx, -expected_dy


def classify_raster(raster_bytes, *, width, height, expected_frequencies=None):
	"""Exakte Palette statt unbewiesener RGB-Nähe; Alpha muss vollständig deckend sein."""
	if not raster_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
		raise ValueError("Die Rasterdatei ist kein PNG")
	with Image.open(BytesIO(raster_bytes)) as image:
		if image.format != "PNG" or image.size != (width, height):
			raise ValueError("PNG-Bildabmessungen stimmen nicht mit der Diagnose überein")
		image.load()
		rgba = image.convert("RGBA")
		pixels = list(rgba.getdata())
	freq = Counter(pixels)
	unknown = {rgba: n for rgba, n in freq.items()
		if rgba[3] != 255 or rgba[:3] not in CATEGORIES}
	if unknown:
		raise ValueError(
			f"{len(unknown)} unbekannte bzw. transparente WMS-Farben – "
			"keine Kronenmasken aus unbestätigten Farben erzeugen: "
			+ str(list(unknown.items())[:8])
		)
	if expected_frequencies is not None:
		reported = {
			tuple(entry["rgba"]): int(entry["pixel"])
			for entry in expected_frequencies
		}
		if reported != freq:
			raise ValueError("PNG-Farbstatistik stimmt nicht mit dem Diagnosebericht überein")
	tree_count = sum(n for color, n in freq.items() if color[:3] == TREE_RGB)
	if tree_count == 0:
		raise ValueError("WMS-Raster enthält keine Baumschicht-Pixel")
	return pixels, dict(Counter({
		name: sum(count for color, count in freq.items() if CATEGORIES[color[:3]] == name)
		for name in CATEGORIES.values()
	}))


def polygonize_tree_pixels(pixels, *, width, height, bbox):
	"""Zusammenhängende Baumzellen als horizontale Runs vereinen.

	Keine Umwandlung jedes der etwa 72.000 Baum-Pixel in ein einzelnes
	Shapely-Objekt nötig; stattdessen nur eine Box pro horizontalem Run.
	"""
	if len(pixels) != width * height:
		raise ValueError("Rasterpixelzahl stimmt nicht mit Bildmaßen überein")
	minx, miny, maxx, maxy = bbox
	dx = (maxx - minx) / width
	dy = (maxy - miny) / height
	runs = []
	pixel_count = 0
	for row in range(height):
		start = None
		for x in range(width + 1):
			is_tree = x < width and pixels[row * width + x][:3] == TREE_RGB
			if is_tree:
				pixel_count += 1
				if start is None:
					start = x
			elif start is not None:
				runs.append(box(minx + start * dx, maxy - (row + 1) * dy,
					minx + x * dx, maxy - row * dy))
				start = None
	if not runs:
		raise ValueError("Kein gültiger Baum-Pixel-Run gefunden")
	combined = union_all(runs)
	if not isinstance(combined, (Polygon, MultiPolygon)) or not combined.is_valid:
		raise ValueError("Raster-Vereinigung ist keine valide Polygongeometrie")
	expected_area = pixel_count * dx * dy
	if not math.isclose(combined.area, expected_area, rel_tol=1e-9, abs_tol=0.001):
		raise ValueError("Raster-Polygonfläche entspricht nicht der Fläche der Baum-Pixel")
	return combined, {"baum_pixel": pixel_count, "baum_runs": len(runs),
		"pixel_breite_m": dx, "pixel_hoehe_m": dy,
		"pixel_flaeche_m2": dx * dy, "baum_pixel_flaeche_m2": expected_area,
		"baum_polygon_flaeche_m2": combined.area,
		"baum_polygon_teilstuecke": len(combined.geoms)
			if isinstance(combined, MultiPolygon) else 1}


def run(*, source=DEFAULT_SOURCE, output=DEFAULT_OUTPUT):
	source = Path(source)
	diagnostic_path = source / "grm2023_wms_diagnose.json"
	diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
	raster, bbox, width, height, dx, dy = validate_source(diagnostic, source)
	pixels, classes = classify_raster(raster.read_bytes(), width=width, height=height,
		expected_frequencies=diagnostic["raster_farbstatistik"]["farben_top"])
	polygon, metrics = polygonize_tree_pixels(pixels, width=width, height=height, bbox=bbox)
	if classes["Baumschicht"] != metrics["baum_pixel"]:
		raise ValueError("Baumschicht-Pixelzahl unterscheidet sich zwischen Raster und Polygon")
	to_wgs84 = Transformer.from_crs(CRS_METRIC, "EPSG:4326", always_xy=True).transform
	geometry = transform(to_wgs84, polygon)
	if not geometry.is_valid:
		raise ValueError("Baumschicht-GeoJSON nach CRS-Transformation ungültig")
	geojson = {"type": "FeatureCollection", "features": [{
		"type": "Feature",
		"properties": {
			"source": "wien_grm2023_wms",
			"source_layer": "GRM2023OGD",
			"original_class": 3,
			"original_class_name": "Baumschicht",
			"pixel_rgb": "#38A800",
			"method": "exact_color_pixel_union_from_wms_rendering",
		},
		"geometry": mapping(geometry),
	}]}
	output = Path(output)
	output.mkdir(parents=True, exist_ok=True)
	geojson_path = output / "baumkronen_grm2023.geojson"
	geojson_path.write_text(json.dumps(geojson, ensure_ascii=False) + "\n",
		encoding="utf-8")
	report = {
		"schema_version": 1,
		"created_utc": datetime.now(timezone.utc).isoformat(),
		"status": "experimenteller WMS-Kronenprovider; kein direkter Quellraster-Export",
		"fachklasse": {"nummer": 3, "name": "Baumschicht",
			"wms_rgb_exakt": "#38A800"},
		"raster_ausrichtung": {"crs": CRS_METRIC, "bbox": bbox,
			"width": width, "height": height},
		"eingaben": {
			"diagnose": str(diagnostic_path),
			"diagnose_sha256": file_sha256(diagnostic_path),
			"wms_png": str(raster), "wms_png_sha256": file_sha256(raster),
			"wms_legende_sha256": diagnostic["wms"]["legende_sha256"],
			"worldfile": str(source / "grm2023_testausschnitt.pgw"),
			"projektion": str(source / "grm2023_testausschnitt.prj"),
		},
		"klassen_pixel": dict(sorted(classes.items())),
		"geometrie": metrics,
		"hinweise": [
			"Die Klassenfarbe wurde anhand der WMS-Legende und der exakt neunfarben Darstellung dieses Ausschnitts geprüft.",
			"Nur deckende Pixel bekannter Farben werden akzeptiert. Unbekannte Farben/Transparenz führen zum Abbruch.",
			"WMS-GetMap kann Quellraster resamplen. Die Anfragegrid-Pixel entsprechen nicht zwingend den 50-cm-Rohdaten.",
			"Baumkronen werden als komplette Polygonmaske ausgegeben; mit Modul measure_canopy_cover separat an Straßenraum schneiden.",
			"Eine größere Baumflächenquote als bei Stammpunkt-Kreisen bedeutet nicht automatisch höhere Genauigkeit.",
		],
		"ausgabe_geojson": str(geojson_path),
	}
	(output / "baumkronen_grm2023_bericht.json").write_text(
		json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	print(f"Baumschicht-Pixel: {metrics['baum_pixel']}")
	print(f"Baumschicht im WMS-Bildausschnitt: {metrics['baum_polygon_flaeche_m2']:.2f} m²")
	print(f"Polygon-Teilstücke: {metrics['baum_polygon_teilstuecke']}")
	print(f"GeoJSON: {geojson_path}")
	print("Straßenraumüberschirmung noch separat mit measure_canopy_cover berechnen.")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
	args = parser.parse_args()
	try:
		run(source=args.source_dir, output=args.out_dir)
	except (OSError, ValueError, TypeError, KeyError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
