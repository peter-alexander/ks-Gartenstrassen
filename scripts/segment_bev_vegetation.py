#!/usr/bin/env python3
"""Methode D3 – explorative Vegetationsobjekte und Kronenkandidaten ohne Höhenmodell.

Low-Gate 0,10: großzügige Kandidaten; High-Gate 0,20: stärkere Signale.
Achtfach verbundene Low-Gate-Regionen werden nur behalten, wenn mindestens
ein High-Gate-Pixel darin vorkommt (Hysterese pro Komponente).

Zusätzlich: RGB-Textur und Objektform auswerten, um *hypothetische* Kronen-
kandidaten von strukturarmen oder unklaren Vegetationsflächen zu unterscheiden.
Keine vermessenen Kronen, kein Überschirmungsgrad, keine Trainingsdaten A/B/C.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw
from pyproj import CRS

from scripts.analyze_bev_vegetation import (
	DEFAULT_INPUT,
	DEFAULT_MIN_SIGNAL,
	index_and_masks,
	read_verified_image,
	validate_manifest,
)
from scripts.probe_bev_wms import WMS_CRS, worldfile_parameters

DEFAULT_OUTPUT = Path("data/processed/baumkronen/bev_segmentierung")
LOW_THRESHOLD = 0.10
HIGH_THRESHOLD = 0.20
# Diese Texturschwellen sind NICHT an Bäumen/Grünflächen validiert.
DEFAULT_CROWN_TEXTURE_DN = 8.0
DEFAULT_FLAT_TEXTURE_DN = 4.0
DEFAULT_MIN_REGION_PIXELS = 12
CLASS_PALETTE = {
	1: (120, 120, 120, 135),  # keine 0,20-Kernpixel, nur schwaches Signal
	2: (220, 160, 40, 155),   # klein, nicht zuverlässig charakterisierbar
	3: (250, 190, 45, 145),   # unklar, aber ausreichend große Vegetation
	4: (15, 190, 60, 175),    # strukturreiche Kronen-KANDIDATEN
	5: (50, 150, 235, 135),   # strukturarme Vegetation, KEIN Baum-Ausschluss
}
LABELS = {
	1: "schwache_vegetation_ohne_kern",
	2: "klein_unklar",
	3: "unklare_vegetation",
	4: "strukturreicher_kronenkandidat",
	5: "strukturarm_nicht_als_baum_ausgeschlossen",
}


def component_regions(low_mask, high_mask, rgb, *, crown_texture_dn=DEFAULT_CROWN_TEXTURE_DN,
	flat_texture_dn=DEFAULT_FLAT_TEXTURE_DN,
	min_region_pixels=DEFAULT_MIN_REGION_PIXELS):
	"""Connected-components auf derselben Pixelmatrix, kein Raster-Resampling.

	Pro Objekt wird der mittlere absolute Grauwertunterschied von RGB-Luminanz
	zwischen *inneren* rechts-/unten-benachbarten Vegetationspixeln berechnet.
	Damit werden Kanten gegen Gebäude/Asphalt nicht als Kronentextur gezählt.
	"""
	if low_mask.size != high_mask.size or low_mask.size != rgb.size:
		raise ValueError("Alle drei Masken/Bilder müssen auf genau demselben Raster liegen")
	if not (math.isfinite(crown_texture_dn) and math.isfinite(flat_texture_dn)
		and 0 <= flat_texture_dn < crown_texture_dn <= 100):
		raise ValueError("Texturschwellen müssen endlich und 0 <= flat < crown <= 100 sein")
	if not isinstance(min_region_pixels, int) or not 1 <= min_region_pixels <= 10000:
		raise ValueError("min_region_pixels muss zwischen 1 und 10000 liegen")
	width, height = low_mask.size
	n = width * height
	low = low_mask.tobytes()
	high = high_mask.tobytes()
	pixels = rgb.convert("RGB").tobytes()
	luma = bytearray(n)
	for i in range(n):
		j = 3 * i
		luma[i] = (77 * pixels[j] + 150 * pixels[j+1] + 29 * pixels[j+2]) >> 8
	visited = bytearray(n)
	classes = bytearray(n)
	objects = []
	class_pixel_counts = Counter()
	class_component_counts = Counter()
	region_count = 0
	max_component_pixels = 0

	for start in range(n):
		if not low[start] or visited[start]:
			continue
		region_count += 1
		visited[start] = 1
		queue = [start]
		head = 0
		min_x, max_x = start % width, start % width
		min_y, max_y = start // width, start // width
		high_count = 0
		adjacent_diff_sum = 0
		adjacent_pair_count = 0
		perimeter_edges = 0
		while head < len(queue):
			i = queue[head]
			head += 1
			x, y = i % width, i // width
			min_x = min(min_x, x)
			max_x = max(max_x, x)
			min_y = min(min_y, y)
			max_y = max(max_y, y)
			if high[i]:
				high_count += 1
			# Mit 4er-Nachbarschaft Textur/Perimeter berechnen; diagonal
			# benachbarte Pixel gehören zur selben 8er-Komponente.
			for dx, dy in ((1, 0), (0, 1)):
				nx, ny = x + dx, y + dy
				if nx < width and ny < height and low[ny * width + nx]:
					adjacent_diff_sum += abs(luma[i] - luma[ny * width + nx])
					adjacent_pair_count += 1
			for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
				nx, ny = x+dx, y+dy
				if nx < 0 or ny < 0 or nx >= width or ny >= height or not low[ny*width+nx]:
					perimeter_edges += 1
			for dx, dy in ((-1,-1), (0,-1), (1,-1),
				(-1,0), (1,0), (-1,1), (0,1), (1,1)):
				nx, ny = x+dx, y+dy
				if nx < 0 or ny < 0 or nx >= width or ny >= height:
					continue
				other = ny * width + nx
				if low[other] and not visited[other]:
					visited[other] = 1
					queue.append(other)
		size = len(queue)
		max_component_pixels = max(max_component_pixels, size)
		mean_texture = (
			adjacent_diff_sum / adjacent_pair_count if adjacent_pair_count else 0.0
		)
		# Der Klassifikator darf nicht als verlässlicher Baum/Gras-Separator
		# gelten. Einzelne Rasenflächen mit Schatten können "baumähnlich"
		# sein; dichte Baumkronen können besonders gleichförmig wirken.
		if not high_count:
			category = 1
		elif size < min_region_pixels:
			category = 2
		elif adjacent_pair_count >= 4 and mean_texture >= crown_texture_dn:
			category = 4
		elif adjacent_pair_count >= 4 and mean_texture <= flat_texture_dn:
			category = 5
		else:
			category = 3
		for i in queue:
			classes[i] = category
		class_pixel_counts[LABELS[category]] += size
		class_component_counts[LABELS[category]] += 1
		bbox_area = (max_x-min_x+1) * (max_y-min_y+1)
		objects.append({
			"id": region_count,
			"klasse": LABELS[category],
			"klasse_code": category,
			"pixel": size,
			"bbox_pixel_inclusive": [min_x, min_y, max_x, max_y],
			"bbox_fuellgrad": round(size / bbox_area, 6),
			"seitenverhaeltnis_bbox": round((max_x-min_x+1) / (max_y-min_y+1), 6),
			"starker_kern_pixel": high_count,
			"starker_kern_anteil": round(high_count / size, 6),
			"rgb_luminanz_nachbartextur_dn": round(mean_texture, 6),
			"nachbarpaar_verwendet": adjacent_pair_count,
			"raster_perimeter_kanten": perimeter_edges,
			"raster_kompaktheit_indikativ": round(
				min(1.0, 4 * math.pi * size / (perimeter_edges * perimeter_edges)), 6),
		})
	stats = {
		"regionen_010": region_count,
		"groesste_region_pixel": max_component_pixels,
		"klassen_regionen": dict(sorted(class_component_counts.items())),
		"klassen_pixel": dict(sorted(class_pixel_counts.items())),
		"starke_020_pixel": sum(1 for v in high if v),
		"schwache_010_pixel": sum(1 for v in low if v),
		"hysterese_pixel": n - sum(1 for c in classes if c == 0 or c == 1),
		"kronenkandidaten_pixel": class_pixel_counts[LABELS[4]],
		"methodik": "8er-Nachbarschaft; Low 0.10, Seed 0.20, Objekttextur RGB Luma DN",
		"textur_schwellen_unvalidiert": {
			"strukturreich_ab_dn": crown_texture_dn,
			"strukturarm_bis_dn": flat_texture_dn,
			"klein_unter_pixel": min_region_pixels,
		},
	}
	return Image.frombytes("L", (width, height), bytes(classes)), objects, stats


def render_classification(rgb, classified):
	"""Original RGB + transparente Klassenfarben, ohne Pixelverschiebung."""
	overlay = Image.new("RGBA", rgb.size)
	colormap = [CLASS_PALETTE.get(value, (0, 0, 0, 0))
		for value in classified.tobytes()]
	overlay.putdata(colormap)
	return Image.alpha_composite(rgb.convert("RGBA"), overlay)


def render_class_mask(classified, codes):
	lookup = bytes(255 if x in codes else 0 for x in range(256))
	return classified.point(lookup)


def run(*, input_dir=DEFAULT_INPUT, output=DEFAULT_OUTPUT, overwrite=False,
	crown_texture_dn=DEFAULT_CROWN_TEXTURE_DN,
	flat_texture_dn=DEFAULT_FLAT_TEXTURE_DN,
	min_region_pixels=DEFAULT_MIN_REGION_PIXELS,
	min_signal=DEFAULT_MIN_SIGNAL):
	"""Neue Ausgabe separat vom WMS und D2; niemals Netzwerkzugriffe."""
	input_dir, output = Path(input_dir), Path(output)
	manifest_file = input_dir / "bev_wms_diagnose.json"
	if not manifest_file.is_file():
		raise FileNotFoundError(f"Diagnose fehlt: {manifest_file}")
	files = [output / f"{stem}.{extension}"
		for stem in ("bev_segmentation_kandidaten", "bev_segmentation_klassen",
			"bev_segmentation_kronenkandidaten", "bev_segmentation_hysterese")
		for extension in ("png", "pgw", "prj")]
	files += [output / "bev_segmentation_bericht.json",
		output / "bev_segmentation_objekte.json"]
	if not overwrite and any(p.exists() for p in files):
		raise FileExistsError(
			"Segmentierung existiert bereits. Neues --out-dir wählen oder --overwrite setzen.")
	report = json.loads(manifest_file.read_text(encoding="utf-8"))
	geometry, evidence = validate_manifest(report)
	rgb, rgb_digest = read_verified_image(input_dir, "rgb", report, geometry)
	infrared, ir_digest = read_verified_image(input_dir, "ir", report, geometry)
	_, masks, vegetation = index_and_masks(rgb, infrared,
		thresholds=(LOW_THRESHOLD, HIGH_THRESHOLD),
		min_signal=min_signal)
	classified, regions, stats = component_regions(masks[LOW_THRESHOLD],
		masks[HIGH_THRESHOLD], rgb, crown_texture_dn=crown_texture_dn,
		flat_texture_dn=flat_texture_dn, min_region_pixels=min_region_pixels)
	rgb_overlay = render_classification(rgb, classified)
	canopy_candidate = render_class_mask(classified, {4})
	hysteresis = render_class_mask(classified, {2, 3, 4, 5})
	# Eine zweite, reine Klassenraster-Visualisierung mit Alpha=0 außerhalb
	# des Vegetationskandidaten. Die Klassen-Codes werden im Bericht erklärt.
	class_visualization = Image.new("RGBA", rgb.size)
	class_visualization.putdata(
		[CLASS_PALETTE.get(value, (0,0,0,0)) for value in classified.tobytes()])
	world = "\n".join(f"{v:.12f}" for v in worldfile_parameters(geometry)) + "\n"
	projection = CRS.from_user_input(WMS_CRS).to_wkt() + "\n"
	output.mkdir(parents=True, exist_ok=True)

	def save_geo(stem, im):
		im.save(output / f"{stem}.png")
		(output / f"{stem}.pgw").write_text(world, encoding="ascii")
		(output / f"{stem}.prj").write_text(projection, encoding="utf-8")

	save_geo("bev_segmentation_kandidaten", rgb_overlay)
	save_geo("bev_segmentation_klassen", class_visualization)
	save_geo("bev_segmentation_kronenkandidaten", canopy_candidate)
	save_geo("bev_segmentation_hysterese", hysteresis)
	objects_file = output / "bev_segmentation_objekte.json"
	objects_file.write_text(json.dumps({
		"schema_version": 1,
		"koordinaten": "Pixelkoordinaten (0-basierter Rasterindex), NICHT GeoJSON",
		"alle_regionen": regions,
	}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	summary = {
		"schema_version": 1,
		"created_utc": datetime.now(timezone.utc).isoformat(),
		"methode": "D3 – explorative Vegetationsobjekte/Kronenkandidaten ohne DSM/DTM",
		"quelle": {
			"wms_diagnose": str(manifest_file),
			"wms_diagnose_sha256": hashlib.sha256(manifest_file.read_bytes()).hexdigest(),
			"rgb_png_sha256": rgb_digest,
			"ir_png_sha256": ir_digest,
			"kernkanal_evidenz": evidence,
			"raster": geometry,
		},
		"schwellen": {"low_vegetation": LOW_THRESHOLD, "strong_signal": HIGH_THRESHOLD,
			"min_signal": min_signal},
		"vegetationswerte": vegetation,
		"segmentierung": stats,
		"klassen": {str(code): label for code, label in LABELS.items()},
		"bilder": [str(p) for p in files if p.suffix == ".png"],
		"objektbericht": str(objects_file),
		"grenzen": [
			"Kein DSM/DTM: Textur und Form allein können Baumkronen nicht zuverlässig von hoher oder niedriger Vegetation trennen.",
			"Klasse 4 ist nur eine unvalidierte Hypothese aus RGB-Luminanzkontrast, keine bestätigte Baumkrone.",
			"Klasse 5 bedeutet NICHT, dass die Region keine Baumkrone ist; gleichmäßige Baumkronen können strukturarm sein.",
			"Bei aneinandergrenzenden Kronen, Hecken und Wiesen entstehen gemeinsame Komponenten.",
			"Keine Baumkronenpolygone/GeoJSON und kein Überschirmungsgrad. Prozentwerte beziehen sich ausschließlich auf WMS-Bildpixel.",
			"Die Indizes beruhen auf unkalibrierten 8-bit-Anzeigewerten, nicht auf radiometrischer NIR/Rot-Reflexion.",
			"Für spätere Validierung müssen voneinander unabhängige Positiv- und Negativregionen manuell beurteilt werden.",
		],
	}
	(output / "bev_segmentation_bericht.json").write_text(
		json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
		encoding="utf-8")
	print("BEV D3: Explorative Segmentierung OHNE Baumkronen-Messung")
	print(f"0,10-Kandidaten: {stats['schwache_010_pixel']} Pixel; "
		f"starke 0,20-Signale: {stats['starke_020_pixel']} Pixel")
	print(f"Hysterese-Kandidaten: {stats['hysterese_pixel']} Pixel; "
		f"{stats['regionen_010']} Komponenten")
	print(f"Strukturreiche *Kronenkandidaten*: {stats['kronenkandidaten_pixel']} Pixel "
		"(unvalidierter RGB-Texturtest)")
	print(f"Visuelle Prüfbilder: {output}/bev_segmentation_kandidaten.png "
		"und bev_segmentation_klassen.png")
	print(f"Bericht: {output}/bev_segmentation_bericht.json")
	return summary


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
	parser.add_argument("--crown-texture-dn", type=float, default=DEFAULT_CROWN_TEXTURE_DN,
		help="Rein explorativer RGB-Texturwert für Kronen-Kandidaten, Standard 8 DN")
	parser.add_argument("--flat-texture-dn", type=float, default=DEFAULT_FLAT_TEXTURE_DN,
		help="Rein explorativer RGB-Texturwert für strukturarme Vegetation, Standard 4 DN")
	parser.add_argument("--min-region-pixels", type=int, default=DEFAULT_MIN_REGION_PIXELS)
	parser.add_argument("--min-signal", type=int, default=DEFAULT_MIN_SIGNAL)
	parser.add_argument("--overwrite", action="store_true")
	args = parser.parse_args()
	try:
		run(input_dir=args.input_dir, output=args.out_dir,
			crown_texture_dn=args.crown_texture_dn,
			flat_texture_dn=args.flat_texture_dn,
			min_region_pixels=args.min_region_pixels,
			min_signal=args.min_signal, overwrite=args.overwrite)
	except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
