#!/usr/bin/env python3
"""Methode D2: Vegetationsindikator aus lokal gespeicherten BEV-WMS-Bildern.

Experimenteller, unkalibrierter *Anzeigewertindex* (NIR-R)/(NIR+R).
Es werden keine Baumkronen erkannt und KEINE Überschirmungswerte ermittelt.

Eingaben: WMS-Diagnosebericht und bev_rgb_test.png / bev_ir_test.png
aus scripts.probe_bev_wms. Kein HTTP-Zugriff und kein DSM/DTM.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pyproj import CRS

from scripts.probe_bev_wms import CORE_CHANNELS, LAYERS, WMS_CRS, worldfile_parameters

DEFAULT_INPUT = Path("data/processed/baumkronen/bev_wms")
DEFAULT_OUTPUT = Path("data/processed/baumkronen/bev_vegetation")
DEFAULT_THRESHOLDS = (0.10, 0.20, 0.30, 0.40)
DEFAULT_MIN_SIGNAL = 20
MAX_PIXELS = 3_000_000
MIN_VALID_PIXELS = 100


def parse_thresholds(text):
	"""Nur eindeutig benennbare Hundertstelschritte, keine Auto-Optimierung."""
	try:
		values = tuple(float(piece.strip()) for piece in text.split(","))
	except ValueError as exc:
		raise ValueError("Schwellen mit Komma trennen, z.B. 0.10,0.20,0.30,0.40") from exc
	if not 1 <= len(values) <= 6 or not all(
		math.isfinite(value) and 0 <= value <= 0.80
		and abs(round(value * 100) - value * 100) < 1e-7
		for value in values
	):
		raise ValueError("1 bis 6 eindeutige Schwellen von 0,00 bis 0,80 in 0,01-Schritten")
	if len(set(round(value * 100) for value in values)) != len(values):
		raise ValueError("Schwellen dürfen nicht doppelt vorkommen")
	return tuple(sorted(values))


def check_core_consistency(report):
	"""Auch ältere BEV-Diagnoseberichte ohne kernkanaele-Feld unterstützen.

	Es werden nur benannte, tatsächlich geprüfte Vergleichspaare akzeptiert.
	Ein widersprüchlicher neuer Kernkanalstatus wird nicht übergangen.
	"""
	comparison = report.get("vergleich") or {}
	groups = comparison.get("kanalgruppen") or {}
	for name, refs in CORE_CHANNELS.items():
		# Die historischen Gruppen haben teilweise andere Referenzen:
		# NIR z.B. IRGB.R statt IR.R. Als gleichwertige Replikatprüfung
		# reichen identische Werte jedes verlangten Paar-Teilstücks.
		for alias, channel_index in refs[1:]:
			item = next((
				item for item in groups.get(name, [])
				if item.get("vergleich") == f"{alias}:RGBA[{channel_index}]"
			), None)
			if item is None or not item.get("intern_konsistent", False):
				raise ValueError(
					f"Nicht belegte Kernkanalkonsistenz: {name} {alias}:RGBA[{channel_index}]. "
					"BEV-WMS-Diagnose zuerst kontrollieren.")
	if comparison.get("kernkanaele_intern_konsistent") is False:
		raise ValueError("BEV-WMS-Kernkanalvergleich nicht bestanden")
	return "aus_einzelvergleich_abgeleitet" if (
		"kernkanaele_intern_konsistent" not in comparison
	) else "in_diagnose_bestaetigt"


def validate_manifest(report):
	if not isinstance(report, dict) or report.get("schema_version") != 1:
		raise ValueError("BEV-WMS-Diagnose JSON schema_version=1 erwartet")
	wms = report.get("wms") or {}
	if wms.get("basis_url") != "https://kataster.bev.gv.at/ortho/ows" or wms.get("version") != "1.3.0":
		raise ValueError("Bericht gehört nicht zum bekannten BEV-Orthofoto-WMS")
	geometry = report.get("raster_ausrichtung") or {}
	if geometry.get("crs") != WMS_CRS:
		raise ValueError("BEV-WMS-Diagnose muss EPSG:3857 enthalten")
	width, height = geometry.get("width"), geometry.get("height")
	if not (isinstance(width, int) and isinstance(height, int)
		and 1 <= width <= 2048 and 1 <= height <= 2048
		and MIN_VALID_PIXELS <= width * height <= MAX_PIXELS):
		raise ValueError("Ungültige oder zu große WMS-Rasterabmessungen")
	bbox = geometry.get("bbox")
	if not (isinstance(bbox, list) and len(bbox) == 4
		and all(isinstance(x, (float, int)) and math.isfinite(x) for x in bbox)
		and bbox[0] < bbox[2] and bbox[1] < bbox[3]):
		raise ValueError("WMS-Projektions-BBOX fehlt oder ist ungültig")
	images = wms.get("bilder") or {}
	for alias in ("rgb", "ir"):
		record = images.get(alias) or {}
		if (record.get("layer") != LAYERS[alias]
			or record.get("status") != "getmap_png_valide"
			or not isinstance(record.get("png_sha256"), str)
			or len(record["png_sha256"]) != 64):
			raise ValueError(f"Kein dokumentierter gültiger GetMap-Abruf für {alias}")
	return geometry, check_core_consistency(report)


def read_verified_image(input_dir, alias, report, geometry):
	file = input_dir / f"bev_{alias}_test.png"
	if not file.is_file():
		raise FileNotFoundError(f"Lokales WMS-Bild fehlt: {file}")
	digest = hashlib.sha256(file.read_bytes()).hexdigest()
	expected = report["wms"]["bilder"][alias]["png_sha256"]
	if digest != expected:
		raise ValueError(f"SHA-256 der BEV-Quelle {alias} stimmt nicht mit WMS-Diagnose überein")
	try:
		with Image.open(file) as src:
			if src.format != "PNG" or src.size != (geometry["width"], geometry["height"]):
				raise ValueError(f"Falsche PNG-Rastergröße oder Format: {file}")
			image = src.convert("RGBA")
	except OSError as exc:
		raise ValueError(f"Nicht lesbares PNG: {file}") from exc
	# Dieselbe Pixel-Georeferenzierung muss in beiden vorhandenen
	# Quell-Worldfiles dokumentiert sein; keine verdeckte Interpolation.
	worldfile = input_dir / f"bev_{alias}_test.pgw"
	projection = input_dir / f"bev_{alias}_test.prj"
	if not worldfile.is_file() or not projection.is_file():
		raise ValueError(f"Raster {alias} hat kein vollständiges PGW/PRJ-Sidecar")
	try:
		parameters = [float(x) for x in worldfile.read_text(encoding="ascii").split()]
		crs = CRS.from_wkt(projection.read_text(encoding="utf-8").strip())
	except (ValueError, OSError) as exc:
		raise ValueError(f"Georeferenzierung für {alias} ungültig") from exc
	expected_params = worldfile_parameters(geometry)
	if (len(parameters) != 6
		or not all(math.isfinite(x) and abs(x-y) <= 1e-6
			for x, y in zip(parameters, expected_params))
		or crs != CRS.from_user_input(WMS_CRS)):
		raise ValueError(f"PNG {alias} besitzt andere Projektion/Pixelgeometrie als der Bericht")
	return image, digest


def index_and_masks(rgb, infrared, thresholds=DEFAULT_THRESHOLDS,
	min_signal=DEFAULT_MIN_SIGNAL):
	if rgb.size != infrared.size:
		raise ValueError("RGB- und IR-PNG dürfen keine verschiedenen Rastergrößen haben")
	if not isinstance(min_signal, int) or not 0 <= min_signal <= 200:
		raise ValueError("min_signal muss zwischen 0 und 200 liegen")
	size = rgb.size
	n = size[0] * size[1]
	r_values = rgb.getchannel("R").tobytes()
	nir_values = infrared.getchannel("R").tobytes()
	a_rgb = rgb.getchannel("A").tobytes()
	a_ir = infrared.getchannel("A").tobytes()
	grey = bytearray(n)
	opaque = bytearray(n)
	binary = {threshold: bytearray(n) for threshold in thresholds}
	counts = {threshold: 0 for threshold in thresholds}
	no_alpha = 0
	low_signal = 0
	valid = 0
	# Ein Index aus 8-bit *Darstellungswerten*. Keine Umdeutung zu
	# reflektierter spektraler Strahlung oder kalibriertem NDVI!
	for i, (red, nir, alpha_rgb, alpha_ir) in enumerate(
		zip(r_values, nir_values, a_rgb, a_ir)
	):
		if alpha_rgb != 255 or alpha_ir != 255:
			no_alpha += 1
			continue
		denom = red + nir
		if denom < min_signal or denom == 0:
			low_signal += 1
			continue
		value = (nir - red) / denom
		grey[i] = max(0, min(255, round((value + 1) * 127.5)))
		opaque[i] = 255
		valid += 1
		for threshold in thresholds:
			if value >= threshold:
				binary[threshold][i] = 255
				counts[threshold] += 1
	if valid < MIN_VALID_PIXELS:
		raise ValueError(f"Zu wenige auswertbare Bildpixel: {valid}")
	index_image = Image.merge("LA", (
		Image.frombytes("L", size, bytes(grey)),
		Image.frombytes("L", size, bytes(opaque)),
	))
	masks = {t: Image.frombytes("L", size, bytes(binary[t]))
		for t in thresholds}
	stats = {
		"pixel_gesamt": n,
		"pixel_verwertbar": valid,
		"pixel_teiltransparent_oder_transparent": no_alpha,
		"pixel_zu_dunkel_oder_summe_null": low_signal,
		"pixel_ungueltig_gesamt": n - valid,
		"signal_min_rot_plus_nir": min_signal,
		"schwellen": [{
			"wert": t,
			"pixel_positiv": counts[t],
			"anteil_an_verwertbaren_pixeln": counts[t] / valid,
			"anteil_am_gesamten_wms_ausschnitt": counts[t] / n,
		} for t in thresholds],
	}
	return index_image, masks, stats


def overlay_rgb(rgb, mask):
	"""Kandidaten ohne Glättung exakt auf derselben Pixelposition einfärben."""
	color = Image.new("RGBA", rgb.size, (10, 180, 60, 0))
	color.putalpha(mask.point(lambda value: 165 if value else 0))
	return Image.alpha_composite(rgb.convert("RGBA"), color)


def make_contact_sheet(rgb, infrared, index_image, overlays, thresholds):
	"""Nicht georeferenziertes Vergleichsblatt; Einzelraster bleiben GIS-fähig."""
	panels = [
		("RGB-Orthofoto", rgb),
		("Infrarot-Graustufen", infrared),
		("WMS-Index: -1 schwarz, +1 weiss", index_image.convert("RGB")),
	]
	panels.extend((f"Index >= {t:.2f}, gruen: Kandidaten", overlays[t])
		for t in thresholds)
	panels.append(("Pruefraster: KEINE Baumkronenklassifikation",
		Image.new("RGB", rgb.size, (40, 45, 48))))
	w, h = rgb.size
	cols = 3
	rows = math.ceil(len(panels) / cols)
	label_height = 34
	canvas = Image.new("RGB", (cols * w, rows * (h + label_height)), (35, 35, 35))
	draw = ImageDraw.Draw(canvas)
	font = ImageFont.load_default()
	for i, (title, image) in enumerate(panels):
		x = (i % cols) * w
		y = (i // cols) * (h + label_height)
		draw.rectangle([x, y, x+w-1, y+label_height-1], fill=(32, 37, 40))
		draw.text((x+9, y+9), title, fill=(255, 255, 255), font=font)
		canvas.paste(image.convert("RGB"), (x, y+label_height))
	return canvas


def run(*, input_dir=DEFAULT_INPUT, output=DEFAULT_OUTPUT,
	thresholds=DEFAULT_THRESHOLDS, min_signal=DEFAULT_MIN_SIGNAL,
	overwrite=False):
	input_dir = Path(input_dir)
	output = Path(output)
	report_file = input_dir / "bev_wms_diagnose.json"
	if not report_file.is_file():
		raise FileNotFoundError(
			f"Der WMS-Diagnosebericht fehlt: {report_file}. "
			"Zuerst probe_bev_wms mit echten Daten ausführen.")
	if not isinstance(thresholds, (tuple, list)) or not thresholds:
		raise ValueError("Mindestens eine Schwelle erforderlich")
	thresholds = parse_thresholds(",".join(str(t) for t in thresholds))
	files = [output / "bev_vegetation_index.png",
		output / "bev_vegetation_index.pgw",
		output / "bev_vegetation_index.prj",
		output / "bev_vegetation_vergleich.png",
		output / "bev_vegetation_bericht.json"]
	for t in thresholds:
		key = f"{round(t*100):03d}"
		for name in (f"bev_veg_maske_{key}", f"bev_veg_overlay_{key}"):
			files.extend([output / f"{name}.{ext}" for ext in ("png", "pgw", "prj")])
	if not overwrite and any(path.exists() for path in files):
		raise FileExistsError(
			"Vegetationsanalyse existiert schon. Anderes --out-dir wählen "
			"oder zum bewussten Ersetzen --overwrite benutzen.")
	source_report = json.loads(report_file.read_text(encoding="utf-8"))
	geometry, evidence = validate_manifest(source_report)
	rgb, rgb_hash = read_verified_image(input_dir, "rgb", source_report, geometry)
	infrared, ir_hash = read_verified_image(input_dir, "ir", source_report, geometry)
	index_image, masks, stats = index_and_masks(
		rgb, infrared, thresholds=thresholds, min_signal=min_signal)
	overlays = {t: overlay_rgb(rgb, masks[t]) for t in thresholds}
	contact = make_contact_sheet(rgb, infrared, index_image, overlays, thresholds)
	world = "\n".join(f"{n:.12f}" for n in worldfile_parameters(geometry)) + "\n"
	projection = CRS.from_user_input(WMS_CRS).to_wkt() + "\n"
	output.mkdir(parents=True, exist_ok=True)

	def write_geo_png(stem, image):
		image.save(output / f"{stem}.png", format="PNG")
		(output / f"{stem}.pgw").write_text(world, encoding="ascii")
		(output / f"{stem}.prj").write_text(projection, encoding="utf-8")

	write_geo_png("bev_vegetation_index", index_image)
	for t in thresholds:
		key = f"{round(t*100):03d}"
		write_geo_png(f"bev_veg_maske_{key}", masks[t])
		write_geo_png(f"bev_veg_overlay_{key}", overlays[t])
	contact.save(output / "bev_vegetation_vergleich.png", format="PNG")
	report = {
		"schema_version": 1,
		"created_utc": datetime.now(timezone.utc).isoformat(),
		"verfahren": "D2 – experimenteller BEV-WMS-Vegetationsindikator, kein kalibrierter NDVI",
		"formel": "(NIR_WMS_8bit - Rot_WMS_8bit) / (NIR_WMS_8bit + Rot_WMS_8bit)",
		"rot": "bev:RGB:RGBA[0]",
		"nahinfrarot": "bev:IR:RGBA[0]",
		"quelle": {
			"beleg": str(report_file),
			"diagnose_sha256": hashlib.sha256(report_file.read_bytes()).hexdigest(),
			"rgb_png_sha256": rgb_hash,
			"ir_png_sha256": ir_hash,
			"kernkanalpruefung": evidence,
			"raster": geometry,
			"aufnahmejahr": source_report.get("aufnahmejahr"),
		},
		"statistik": stats,
		"darstellung": {
			"index_png": "L-Grauwert mit Alpha: -1=0, 0=128, +1=255, invalid transparent",
			"masken": "L-Grauwert 255=Kandidat, 0=kein Kandidat/ungueltig",
			"overlay": "RGB plus halbtransparente gruene Kandidatenpixel",
			"vergleich": "Nicht georeferenziertes Kontaktblatt",
		},
		"ausgaben": [str(path) for path in files],
		"grenzen": [
			"Nur gerenderte 8-bit-WMS-Bildwerte: keine radiometrischen Reflexionsgrade, kein wissenschaftlich kalibrierter NDVI.",
			"Schwellen sind reine Explorationsvarianten; nicht fachlich optimiert oder als Bäume klassifiziert.",
			"Positive Pixel können Baumkronen, Sträucher, Rasen, Beete, Dachbegrünung oder andere Vegetation enthalten.",
			"Hohe Sträucher und niedrige Bäume lassen sich ohne Höhen-/Objektinformation nicht zuverlässig trennen.",
			"Schattige Vegetation kann durch die Mindest-Signalprüfung verloren gehen.",
			"Bildanteile sind keine Straßenraum- und keine Überschirmungsgrade.",
		],
	}
	(output / "bev_vegetation_bericht.json").write_text(
		json.dumps(report, ensure_ascii=False, indent=2) + "\n",
		encoding="utf-8")
	print("BEV Methode D2 – experimenteller WMS-Vegetationsindikator (nicht kalibriert)")
	print(f"Raster: {rgb.width} × {rgb.height} px, verwertbar {stats['pixel_verwertbar']}/{stats['pixel_gesamt']}")
	for item in stats["schwellen"]:
		print(f"  Index >= {item['wert']:.2f}: {item['pixel_positiv']} Pixel "
			f"({100*item['anteil_an_verwertbaren_pixeln']:.2f}% der gültigen Bildpixel)")
	print(f"Visuelle Vorschau: {output / 'bev_vegetation_vergleich.png'}")
	print(f"Statistik: {output / 'bev_vegetation_bericht.json'}")
	print("Noch keine Baumkronen ermittelt; keine Überschirmungsgrade berechnet.")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
	parser.add_argument("--thresholds", type=parse_thresholds,
		default=DEFAULT_THRESHOLDS,
		help="Explorative Schwellen; 1–6 Werte, z.B. 0.10,0.20,0.30,0.40")
	parser.add_argument("--min-signal", type=int, default=DEFAULT_MIN_SIGNAL,
		help="Mindestwert für Rot+NIR (8-bit Anzeigewerte), Standard 20")
	parser.add_argument("--overwrite", action="store_true",
		help="Vorhandene Vegetationsanalyse bewusst ersetzen")
	args = parser.parse_args()
	try:
		run(input_dir=args.input_dir, output=args.out_dir,
			thresholds=args.thresholds, min_signal=args.min_signal,
			overwrite=args.overwrite)
	except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
