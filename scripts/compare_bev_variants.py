#!/usr/bin/env python3
"""Vergleichsrechnung aller bisherigen BEV-D-Varianten auf demselben Straßenraum.

Berechnet geometrisch exakte Schnitte der *pixelisierten* D2-/D3-Masken
mit der bestehenden Straßenraum-Geometrie in EPSG:31256. Das Pixelmodell
bleibt dennoch eine WMS-0,5m-Abtastung: Genauigkeit der Kronenerkennung
ist weder durch Polygonisierung noch durch Flächenmessung nachgewiesen.

D2: alle sieben tatsächlich getesteten Schwellen (0,10 bis 0,40)
D3: Hysterese, Kronenkandidaten, Kronenkandidaten + Unklar, alle fünf Klassen
A/B/C: unabhängige Referenzwerte, sofern entsprechende Dateien vorhanden.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from pyproj import Transformer
from shapely import union_all
from shapely.geometry import box
from shapely.ops import transform

from scripts.analyze_bev_vegetation import (
	DEFAULT_INPUT, DEFAULT_MIN_SIGNAL, index_and_masks,
	read_verified_image, validate_manifest,
)
from scripts.fmzk_source import load_polygons
from scripts.measure_ground_greening import load_street_mask
from scripts.measure_canopy_cover import measure_coverage, read_crown_polygons
from scripts.segment_bev_vegetation import (
	component_regions, render_class_mask, LABELS,
	DEFAULT_CROWN_TEXTURE_DN, DEFAULT_FLAT_TEXTURE_DN,
	DEFAULT_MIN_REGION_PIXELS,
)

DEFAULT_STREET = Path("data/processed/street_space/fmzk_strassenraum.geojson")
DEFAULT_FMZK = Path("data/processed/fmzk_test.gpkg")
DEFAULT_OUTPUT = Path("data/processed/baumkronen/bev_variantenvergleich")
DEFAULT_D3_REPORT = Path("data/processed/baumkronen/bev_segmentierung/bev_segmentation_bericht.json")
D2_THRESHOLDS = (0.10, 0.15, 0.17, 0.18, 0.20, 0.30, 0.40)
REFERENCE_PATHS = {
	"A_Wien": Path("data/processed/baumkronen/baumkronen_kreise.geojson"),
	"B_Wien_OSM": Path("data/processed/baumkronen/variante_b/baumkronen_kombiniert.geojson"),
	"C_GRM2023": Path("data/processed/baumkronen/grm2023/processed/baumkronen_grm2023.geojson"),
}
# Nur getrennte Interpretationen; keine optimierte Kronenquote.
D3_CLASSES = {
	"D3_strukturreiche_kronenkandidaten": {4},
	"D3_kronenkandidaten_plus_unklar": {3, 4},
	"D3_unklare_vegetation": {3},
	"D3_strukturarme_vegetation": {5},
	"D3_kleine_unklare_objekte": {2},
	"D3_schwache_vegetation_ohne_kern": {1},
	"D3_hysterese_010_mit_020_kern": {2, 3, 4, 5},
}
SELECTED_IOU = {
	"D2_schwelle_010", "D2_schwelle_020",
	"D3_strukturreiche_kronenkandidaten",
	"D3_kronenkandidaten_plus_unklar",
	"D3_hysterese_010_mit_020_kern",
}


def grid_geometry(geometry):
	if geometry.get("crs") != "EPSG:3857":
		raise ValueError("WMS-Testgitter muss EPSG:3857 sein")
	x0, y0, x1, y1 = geometry["bbox"]
	width, height = geometry["width"], geometry["height"]
	if not (x0 < x1 and y0 < y1 and 0 < width <= 2048 and 0 < height <= 2048):
		raise ValueError("Ungültiges WMS-Testgitter")
	return x0, y0, x1, y1, width, height


def raster_extent_in_metric(geometry):
	x0, y0, x1, y1, _, _ = grid_geometry(geometry)
	project = Transformer.from_crs("EPSG:3857", "EPSG:31256", always_xy=True).transform
	# Transformation des densifizierten Pixelgitter-Randes, nicht nur seiner Ecken.
	return transform(project, box(x0, y0, x1, y1).segmentize(5))


def runs_to_metric_union(mask, geometry, *, street_bounds_metric=None):
	"""Pixelgenaue Flächen: jede zusammenhängende horizontale 255-Run ist Rechteck.

	Rechtecke im originalen EPSG:3857-WMS-Gitter anlegen, vereinigen,
	anschließend in metrisches EPSG:31256 transformieren. Keine rasterisierte
	Straßenmaske, kein bloßes Abzählen von Pixelzentren. Randzellen werden
	gegen das Straßenpolygon geometrisch angeschnitten.
	"""
	x0, y0, x1, y1, width, height = grid_geometry(geometry)
	if mask.size != (width, height) or mask.mode != "L":
		raise ValueError("Masken müssen L-Binärbilder auf dem ursprünglichen WMS-Raster sein")
	dx, dy = (x1-x0)/width, (y1-y0)/height
	dat = mask.tobytes()
	if any(v not in (0, 255) for v in dat):
		raise ValueError("Masken dürfen ausschließlich die Werte 0 und 255 enthalten")
	window = None
	if street_bounds_metric is not None:
		to_wms = Transformer.from_crs("EPSG:31256", "EPSG:3857", always_xy=True).transform
		# Straßenraum-BBOX plus 2 Rasterzellen Sicherheitsrand – kein
		# fachlicher Clip, nur um unnötige Privatflächen zu überspringen.
		window = transform(to_wms, box(*street_bounds_metric).segmentize(5)).bounds
	rectangles = []
	pixel_count = 0
	for row in range(height):
		top = y1-row*dy
		bottom = top-dy
		if window is not None and (bottom > window[3] or top < window[1]):
			continue
		start = row*width
		end = start+width
		i = start
		while i < end:
			if dat[i] == 0:
				i += 1
				continue
			left = i
			while i < end and dat[i] == 255:
				i += 1
			rl, rr = x0+(left-start)*dx, x0+(i-start)*dx
			if window is not None and (rr < window[0] or rl > window[2]):
				continue
			rectangles.append(box(rl, bottom, rr, top))
			pixel_count += i-left
	if not rectangles:
		return None, {"pixel_in_bbox": 0, "horizontal_runs": 0}
	merged = union_all(rectangles)
	to_metric = Transformer.from_crs("EPSG:3857", "EPSG:31256", always_xy=True).transform
	metric = transform(to_metric, merged)
	if metric.is_empty or not metric.is_valid:
		raise ValueError("Masken-Polygonisierung hat eine ungültige Fläche erzeugt")
	return metric, {
		"pixel_in_bbox": pixel_count,
		"horizontal_runs": len(rectangles),
		"raster_polygon_union_m2": metric.area,
	}


def nonempty_measure(street, geometry):
	"""Gemeinsame metrische Schnittlogik mit A/B/C, auch bei 0 Pixeln."""
	if geometry is None or geometry.is_empty:
		return {
			"strassenraum_m2": street.area,
			"bedeckt_m2": 0.0,
			"bedeckung_pct": 0.0,
			"ausserhalb_strassenraum_m2": 0.0,
			"maskenunion_m2": 0.0,
		}, None
	metrics, clipped = measure_coverage(street, geometry)
	return {
		"strassenraum_m2": metrics["strassenraum_m2"],
		"bedeckt_m2": metrics["ueberschirmt_m2"],
		"bedeckung_pct": metrics["ueberschirmungsgrad_pct"],
		"ausserhalb_strassenraum_m2": metrics["ausserhalb_strassenraum_m2"],
		"maskenunion_m2": metrics["baumkronen_union_m2"],
	}, clipped


def check_d3_report(path, *, rgb_digest, ir_digest, comparison):
	"""Bereits lokal berechneten D3-Lauf gegen Neuberechnung prüfen."""
	if not Path(path).is_file():
		return {"status": "nicht_vorhanden", "bericht": str(path)}
	report = json.loads(Path(path).read_text(encoding="utf-8"))
	source = report.get("quelle", {})
	if source.get("rgb_png_sha256") != rgb_digest or source.get("ir_png_sha256") != ir_digest:
		raise ValueError("D3-Bericht basiert auf anderen RGB-/IR-WMS-Quellbildern")
	schw = report.get("schwellen") or {}
	if schw.get("low_vegetation") != .1 or schw.get("strong_signal") != .2 or schw.get("min_signal") != 20:
		raise ValueError("D3-Bericht verwendet andere Vegetationsschwellen/Minimalsignal")
	previous = report.get("segmentierung") or {}
	for key in ("klassen_pixel", "regionen_010", "hysterese_pixel", "kronenkandidaten_pixel"):
		if previous.get(key) != comparison.get(key):
			raise ValueError(f"D3-Neuberechnung weicht vom gespeicherten Bericht ab: {key}")
	for key, value in (
		("strukturreich_ab_dn", DEFAULT_CROWN_TEXTURE_DN),
		("strukturarm_bis_dn", DEFAULT_FLAT_TEXTURE_DN),
		("klein_unter_pixel", DEFAULT_MIN_REGION_PIXELS),
	):
		if previous.get("textur_schwellen_unvalidiert", {}).get(key) != value:
			raise ValueError(f"D3-Bericht verwendet abweichende Texturkonfiguration: {key}")
	return {
		"status": "reproduktion_bestaetigt",
		"bericht": str(path),
		"sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
	}


def measure_variants(street, mask_dict, geometry):
	"""Die D-Masken vollständig und ohne gemeinsame Flächen-Doppelzählung messen."""
	raster_extent = raster_extent_in_metric(geometry)
	missing = street.difference(raster_extent).area
	if missing > max(0.05, street.area * 0.000001):
		raise ValueError(
			f"BEV-WMS-Bild deckt den Straßenraum nicht vollständig ab: "
			f"{missing:.3f} m² fehlen. Ergebnisse wären systematisch zu niedrig.")
	results = {}
	clipped = {}
	for name, mask in mask_dict.items():
		shape_metric, debug = runs_to_metric_union(mask, geometry,
			street_bounds_metric=street.bounds)
		metrics, inside = nonempty_measure(street, shape_metric)
		results[name] = {
			"pixel_positiv_gesamtbild": mask.histogram()[255],
			"maskenmetrik": metrics,
			"polygonisierung": debug,
		}
		if name in SELECTED_IOU:
			clipped[name] = inside
	return results, clipped


def reference_comparison(street, clipped_masks, reference_paths):
	"""Optionale Referenzen; gegenseitige Überlappung bedeutet NICHT Genauigkeit."""
	references = {}
	overlaps = []
	for name, path in reference_paths.items():
		path = Path(path)
		if not path.is_file():
			references[name] = {"status": "lokale_quelle_fehlt", "pfad": str(path)}
			continue
		geometry, source_meta = read_crown_polygons(path)
		value, reference_clip = measure_coverage(street, geometry)
		references[name] = {
			"status": "gemessen",
			"pfad": str(path), "quelle": source_meta,
			"flaeche_m2": value["ueberschirmt_m2"],
			"anteil_pct": value["ueberschirmungsgrad_pct"],
		}
		for d_name, d_shape in clipped_masks.items():
			intersection = (
				d_shape.intersection(reference_clip).area
				if d_shape is not None else 0.0
			)
			d_area = d_shape.area if d_shape is not None else 0.0
			union_area = d_area + reference_clip.area - intersection
			overlaps.append({
				"d_variante": d_name, "referenz": name,
				"gemeinsam_m2": intersection,
				"nur_d_m2": max(0.0, d_area - intersection),
				"nur_referenz_m2": max(0.0, reference_clip.area - intersection),
				"iou": intersection/union_area if union_area > 0 else None,
			})
	return references, overlaps


def run(*, input_dir=DEFAULT_INPUT, street=DEFAULT_STREET, fmzk=DEFAULT_FMZK,
	output=DEFAULT_OUTPUT, d3_report=DEFAULT_D3_REPORT,
	references=REFERENCE_PATHS):
	output = Path(output)
	report_path = output / "bev_varianten_strassenraum_vergleich.json"
	if report_path.exists():
		raise FileExistsError(
			f"Vergleichsbericht existiert bereits: {report_path}. "
			"Für neuen Lauf ein anderes --out-dir wählen.")
	manifest_path = Path(input_dir) / "bev_wms_diagnose.json"
	if not manifest_path.is_file():
		raise FileNotFoundError(f"BEV-WMS-Diagnose nicht vorhanden: {manifest_path}")
	diagnosis = json.loads(manifest_path.read_text(encoding="utf-8"))
	geometry, evidence = validate_manifest(diagnosis)
	rgb, rgb_hash = read_verified_image(input_dir, "rgb", diagnosis, geometry)
	ir, ir_hash = read_verified_image(input_dir, "ir", diagnosis, geometry)
	_, masks, raster_summary = index_and_masks(rgb, ir,
		thresholds=D2_THRESHOLDS, min_signal=DEFAULT_MIN_SIGNAL)
	classified, _, d3_summary = component_regions(
		masks[.10], masks[.20], rgb)
	checked_d3 = check_d3_report(d3_report,
		rgb_digest=rgb_hash, ir_digest=ir_hash, comparison=d3_summary)
	variants = {f"D2_schwelle_{round(t*100):03d}": masks[t]
		for t in D2_THRESHOLDS}
	for name, codes in D3_CLASSES.items():
		variants[name] = render_class_mask(classified, codes)
	_, fmzk_manifest, clip, _ = load_polygons(fmzk)
	street_geom, street_meta = load_street_mask(street, clip)
	values, clipped = measure_variants(street_geom, variants, geometry)
	ref_stats, ref_overlaps = reference_comparison(street_geom, clipped, references)
	report = {
		"schema_version": 1,
		"created_utc": datetime.now(timezone.utc).isoformat(),
		"status": "EXPLORATIVE BEV-D-MASKENBEDECKUNG – KEIN BESTAETIGTER BAUMKRONEN-UEBERSCHIRMUNGSGRAD",
		"bereich": {
			"fmzk": str(fmzk), "bbox_lon_lat": fmzk_manifest["bbox_lon_lat"],
			"strassenraum_geojson": str(street),
			"strassenraum_sha256": street_meta["masken_sha256"],
			"strassenraum_m2": street_geom.area,
		},
		"quelle": {
			"diagnose_json": str(manifest_path),
			"diagnose_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
			"rgb_png_sha256": rgb_hash, "ir_png_sha256": ir_hash,
			"kernkanalpruefung": evidence,
			"wms_raster": geometry,
			"d3_bericht": checked_d3,
		},
		"d2": {"schwellen": D2_THRESHOLDS, "statistik_gesamtbild": raster_summary},
		"d3": {
			"schwellen": {"low": 0.10, "strong": 0.20,
				"textur_stark_ab_dn": DEFAULT_CROWN_TEXTURE_DN,
				"textur_arm_bis_dn": DEFAULT_FLAT_TEXTURE_DN,
				"objekt_min_pixel": DEFAULT_MIN_REGION_PIXELS},
			"klassen": {str(k): value for k, value in LABELS.items()},
			"statistik": d3_summary,
		},
		"varianten": values,
		"referenzen": ref_stats,
		"raeumliche_vergleiche": ref_overlaps,
		"messmethode": (
			"Original BEV-WMS-Pixel als EPSG:3857-Rechtecke polygonisiert; "
			"geometrisch vereinigt, in EPSG:31256 transformiert und mit exakt "
			"derselben Straßenraum-Geometrie wie A/B/C geschnitten. "
			"Kein Rasterisieren oder Zentroidtest des Straßenraums."
		),
		"einschraenkungen": [
			"Masken sind auf WMS-Bildauflösung und gerenderte 8-bit-Kanäle beschränkt.",
			"D2-Schwellen bedeuten Vegetationskandidaten, nicht nur Bäume.",
			"D3-Klassen sind texturabhängige, unvalidierte Kronenkandidaten; keine nachgewiesene Baumklassifikation.",
			"Eine Flächenquote kann durch bodennahe Vegetation oder fehlerhafte Segmentierung über-/unterschätzen.",
			"Vergleich mit A/B/C ist deskriptiv; Übereinstimmung/IoU misst keine Genauigkeit.",
			"Straßenraumgrenze selbst vorläufig; keine Aussagen für ganz Wien.",
			"Zahl in allen D-Varianten ist Flächenbedeckung einer jeweiligen Rastermaske IM Straßenraum – kein Wien-Plan-Überschirmungsgrad.",
		],
	}
	output.mkdir(parents=True, exist_ok=True)
	report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
		encoding="utf-8")
	print(f"Straßenraum: {street_geom.area:.2f} m²")
	print("D-Masken: VORLÄUFIGE Raster-Bedeckung, keine bestätigte Baumüberschirmung")
	for name, item in values.items():
		metric = item["maskenmetrik"]
		print(f"  {name}: {metric['bedeckt_m2']:.2f} m² / "
			f"{metric['bedeckung_pct']:.2f} %")
	print("Zum Vergleich (A/B/C):")
	for name, stat in ref_stats.items():
		if stat["status"] == "gemessen":
			print(f"  {name}: {stat['flaeche_m2']:.2f} m² / {stat['anteil_pct']:.2f} %")
		else:
			print(f"  {name}: nicht verfügbar ({stat['pfad']})")
	print(f"Bericht: {report_path}")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
	parser.add_argument("--street-geojson", type=Path, default=DEFAULT_STREET)
	parser.add_argument("--fmzk", type=Path, default=DEFAULT_FMZK)
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
	parser.add_argument("--d3-report", type=Path, default=DEFAULT_D3_REPORT)
	args = parser.parse_args()
	try:
		run(input_dir=args.input_dir, street=args.street_geojson,
			fmzk=args.fmzk, output=args.out_dir, d3_report=args.d3_report)
	except (OSError, ValueError, KeyError, TypeError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
