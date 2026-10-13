#!/usr/bin/env python3
"""Diagnose der Wiener WMS-Baumschicht GRM2023OGD (noch KEINE Kronenmessung).

Sichert GetCapabilities, einen räumlich referenzierten PNG-Ausschnitt,
optional die WMS-Legende und einen transparenten Pixel-/Farbenbericht.
Darstellungsfarben werden NICHT automatisch der Klasse 3 zugeordnet.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from PIL import Image
from pyproj import CRS, Transformer
from shapely.ops import transform

from scripts.fmzk_source import load_polygons

WMS_URL = "https://data.wien.gv.at/daten/wms"
LAYER = "GRM2023OGD"
WMS_VERSION = "1.1.1"  # keine Achsenreihenfolge-Mehrdeutigkeit wie bei WMS 1.3.0
DEFAULT_FMZK = Path("data/processed/fmzk_test.gpkg")
DEFAULT_OUTPUT = Path("data/processed/baumkronen/grm2023")
MAX_RESPONSE_BYTES = 15_000_000
MAX_IMAGE_SIDE = 2048
MAX_IMAGE_PIXELS = 3_000_000


def local_tag(tag):
	return tag.rsplit("}", 1)[-1].split(":")[-1]


def children(node, name):
	return [child for child in node if local_tag(child.tag) == name]


def child_text(node, name):
	return next((child.text.strip() for child in children(node, name)
		if child.text and child.text.strip()), None)


def parse_capabilities(content, *, layer=LAYER):
	if len(content) > MAX_RESPONSE_BYTES:
		raise ValueError("GetCapabilities ist zu groß")
	try:
		root = ET.fromstring(content)
	except ET.ParseError as exc:
		raise ValueError(f"Ungültiges WMS GetCapabilities XML: {exc}") from exc
	if local_tag(root.tag) not in ("WMT_MS_Capabilities", "WMS_Capabilities"):
		raise ValueError("GetCapabilities lieferte kein WMS-Capabilities-Dokument")
	capabilities = next(iter(children(root, "Capability")), None)
	if capabilities is None:
		raise ValueError("WMS-Capability fehlt")
	root_layers = children(capabilities, "Layer")
	if not root_layers:
		raise ValueError("WMS-Layerbaum fehlt")
	found = None

	def visit(node, inherited):
		nonlocal found
		if found is not None:
			return
		srs = set(inherited)
		for crs_tag in ("SRS", "CRS"):
			for item in children(node, crs_tag):
				if item.text:
					srs.update(value.upper() for value in item.text.split())
		if child_text(node, "Name") == layer:
			styles = []
			for style in children(node, "Style"):
				info = {"name": child_text(style, "Name"),
					"title": child_text(style, "Title")}
				styles.append(info)
			found = {
				"name": layer,
				"title": child_text(node, "Title"),
				"unterstuetzte_srs": sorted(srs),
				"stile": styles,
				"queryable": node.attrib.get("queryable"),
			}
			return
		for nested in children(node, "Layer"):
			visit(nested, srs)

	for layer_root in root_layers:
		visit(layer_root, set())
	if found is None:
		raise ValueError(f"WMS-Layer {layer} nicht in GetCapabilities gefunden")
	request = next(iter(children(capabilities, "Request")), None)
	if request is None:
		raise ValueError("WMS-Capability/Request fehlt")
	operations = {}
	for item in request:
		name = local_tag(item.tag)
		operations[name] = [form.text.strip() for form in children(item, "Format")
			if form.text and form.text.strip()]
	found["operationen"] = operations
	if not any(fmt.lower() == "image/png" for fmt in operations.get("GetMap", [])):
		raise ValueError("WMS bietet kein image/png für GetMap")
	return found


def choose_srs(capabilities):
	available = capabilities["unterstuetzte_srs"]
	for crs in ("EPSG:31256", "EPSG:3857"):
		if crs in available:
			return crs
	raise ValueError(
		"GetCapabilities bietet weder EPSG:31256 noch EPSG:3857: "
		+ ", ".join(available[:20])
	)


def image_request_geometry(clip, crs, *, padding_m=10, pixel_size_m=0.5):
	if not (0 <= padding_m <= 40):
		raise ValueError("padding_m muss zwischen 0 und 40 liegen")
	if not (0.25 <= pixel_size_m <= 2):
		raise ValueError("pixel_size_m muss zwischen 0.25 und 2 liegen")
	buffered = clip.buffer(padding_m).envelope
	metre_bounds = buffered.bounds
	# Breite/Höhe in tatsächlichen Metern des lokalen Testausschnitts
	width = math.ceil((metre_bounds[2] - metre_bounds[0]) / pixel_size_m)
	height = math.ceil((metre_bounds[3] - metre_bounds[1]) / pixel_size_m)
	if (not 1 <= width <= MAX_IMAGE_SIDE or not 1 <= height <= MAX_IMAGE_SIDE
		or width * height > MAX_IMAGE_PIXELS):
		raise ValueError(
			f"Rasteranfrage {width}×{height} ist zu groß; "
			"Pixelgröße erhöhen oder Gebiet verkleinern"
		)
	if crs == "EPSG:31256":
		bbox = metre_bounds
	else:
		transform_to = Transformer.from_crs(
			"EPSG:31256", crs, always_xy=True
		).transform
		bbox = transform(transform_to, buffered).bounds
	if not all(math.isfinite(v) for v in bbox):
		raise ValueError("Ungültige WMS-Koordinaten")
	return {"crs": crs, "bbox": list(bbox), "width": width, "height": height,
		"sampling_ground_m_per_pixel": pixel_size_m,
		"requested_padding_m": padding_m,
		"sampling_warning": (
			"GetMap liefert ein auf das Anfragegitter gerendertes Raster. "
			"0,5 m Pixelgröße im Request garantiert KEINEN unveränderten "
			"Zugriff auf das 50-cm-Quellraster."
		)}


def wms_url(request, **params):
	values = [("service", "WMS"), ("version", WMS_VERSION),
		("request", request)]
	values.extend(params.items())
	return WMS_URL + "?" + urlencode(values)


def get_map_url(geometry):
	return wms_url("GetMap",
		layers=LAYER, styles="", srs=geometry["crs"],
		bbox=",".join(format(n, ".9f") for n in geometry["bbox"]),
		width=geometry["width"], height=geometry["height"],
		format="image/png", transparent="TRUE", bgcolor="0xFFFFFF")


def get_legend_url():
	return wms_url("GetLegendGraphic", layer=LAYER, style="", format="image/png")


def request_bytes(url, *, limit=MAX_RESPONSE_BYTES):
	request = Request(url, headers={
		"User-Agent": "ks-Gartenstrassen/1.0 (lokale Testgebiet-Analyse)",
		"Accept": "image/png,application/xml,text/xml,*/*",
	})
	with urlopen(request, timeout=50) as response:
		result = response.read(limit + 1)
	if len(result) > limit:
		raise ValueError(f"WMS-Antwort überschreitet {limit} Bytes")
	return result


def require_png(content, *, expected_size=None):
	if not content.startswith(b"\x89PNG\r\n\x1a\n"):
		raise ValueError(
			"Der Dienst lieferte keine PNG-Bilddaten (evtl. WMS-ServiceException): "
			+ repr(content[:250])
		)
	try:
		with Image.open(BytesIO(content)) as im:
			if im.format != "PNG":
				raise ValueError("WMS-Antwort ist kein echtes PNG")
			im.load()
			size = im.size
	except (OSError, Image.DecompressionBombError) as exc:
		raise ValueError(f"Nicht lesbares PNG: {exc}") from exc
	if (size[0] < 1 or size[1] < 1 or size[0] > MAX_IMAGE_SIDE
		or size[1] > MAX_IMAGE_SIDE or size[0] * size[1] > MAX_IMAGE_PIXELS):
		raise ValueError("WMS-PNG hat eine unerwartete Bildgröße")
	if expected_size is not None and tuple(expected_size) != size:
		raise ValueError(f"WMS-PNG {size} ≠ angefragte Bildgröße {expected_size}")
	return size


def raster_inventory(content, *, maximum_colors=30):
	require_png(content)
	with Image.open(BytesIO(content)) as im:
		original_mode = im.mode
		rgba = im.convert("RGBA")
		frequencies = Counter(rgba.getdata())
		opaque = sum(n for color, n in frequencies.items() if color[3] == 255)
		translucent = sum(n for color, n in frequencies.items()
			if 0 < color[3] < 255)
		transparent = sum(n for color, n in frequencies.items() if color[3] == 0)
		return {
			"bildformat": im.format,
			"bildmodus": original_mode,
			"breite": im.width,
			"hoehe": im.height,
			"pixel_gesamt": im.width * im.height,
			"verschiedene_rgba_farben": len(frequencies),
			"pixel_opaque": opaque,
			"pixel_teiltransparent": translucent,
			"pixel_transparent": transparent,
			"farben_top": [{
				"rgba": list(color),
				"hex_rgb": "#{:02X}{:02X}{:02X}".format(*color[:3]),
				"pixel": count,
			} for color, count in frequencies.most_common(maximum_colors)],
		}


def worldfile_parameters(geometry):
	"""WMS-PNG zentergenau im angegebenen Projektions-CRS verorten."""
	minx, miny, maxx, maxy = geometry["bbox"]
	width, height = geometry["width"], geometry["height"]
	pixel_x = (maxx - minx) / width
	pixel_y = -(maxy - miny) / height
	return (pixel_x, 0.0, 0.0, pixel_y,
		minx + pixel_x / 2, maxy + pixel_y / 2)


def run(*, fmzk=DEFAULT_FMZK, output=DEFAULT_OUTPUT,
	padding_m=10, pixel_size_m=0.5):
	_, manifest, clip, _ = load_polygons(fmzk)
	cap_url = wms_url("GetCapabilities")
	cap_bytes = request_bytes(cap_url)
	meta = parse_capabilities(cap_bytes)
	crs = choose_srs(meta)
	geometry = image_request_geometry(clip, crs,
		padding_m=padding_m, pixel_size_m=pixel_size_m)
	map_url = get_map_url(geometry)
	raster_bytes = request_bytes(map_url)
	require_png(raster_bytes, expected_size=(geometry["width"], geometry["height"]))
	inventory = raster_inventory(raster_bytes)
	legend_url = get_legend_url()
	legend_bytes = None
	legend_status = "nicht_verfuegbar"
	try:
		raw = request_bytes(legend_url, limit=2_000_000)
		require_png(raw)
		legend_bytes = raw
		legend_status = "png_empfangen_nicht_fachlich_interpretiert"
	except (OSError, ValueError) as exc:
		legend_status = f"legendendienst_nicht_verfuegbar: {exc}"
	output = Path(output)
	output.mkdir(parents=True, exist_ok=True)
	(output / "getcapabilities.xml").write_bytes(cap_bytes)
	(output / "grm2023_testausschnitt.png").write_bytes(raster_bytes)
	(output / "grm2023_testausschnitt.pgw").write_text(
		"\n".join(format(v, ".12f") for v in worldfile_parameters(geometry)) + "\n",
		encoding="ascii")
	(output / "grm2023_testausschnitt.prj").write_text(
		CRS.from_user_input(crs).to_wkt() + "\n", encoding="utf-8")
	if legend_bytes is not None:
		(output / "grm2023_legende.png").write_bytes(legend_bytes)
	report = {
		"schema_version": 1,
		"zeitpunkt_utc": datetime.now(timezone.utc).isoformat(),
		"status": "DIAGNOSE – keine validierte Kronenklassifikation oder Überschirmungsmessung",
		"datensatz": "Grünraummonitoring 2023 Wien",
		"bekannte_fachklasse": {"wert": 3, "bedeutung": "Baumschicht"},
		"hinweis": "Fachklasse 3 ist NICHT automatisch ein Pixelwert oder eine RGB-Farbe des WMS-GetMap-Bilds.",
		"testgebiet_bbox_lon_lat": manifest["bbox_lon_lat"],
		"fmzk_quelle": str(fmzk),
		"wms": {"basis_url": WMS_URL, "version": WMS_VERSION,
			"layer": LAYER, "getcapabilities_url": cap_url,
			"getcapabilities_sha256": hashlib.sha256(cap_bytes).hexdigest(),
			"layer_metadaten": meta,
			"getmap_url": map_url, "getmap_sha256": hashlib.sha256(raster_bytes).hexdigest(),
			"getlegend_url": legend_url, "legende_status": legend_status,
			"legende_sha256": (hashlib.sha256(legend_bytes).hexdigest()
				if legend_bytes else None)},
		"raster_ausrichtung": geometry,
		"raster_farbstatistik": inventory,
		"ausgabe": {
			"capabilities": str(output / "getcapabilities.xml"),
			"wms_png": str(output / "grm2023_testausschnitt.png"),
			"worldfile_pgw": str(output / "grm2023_testausschnitt.pgw"),
			"projektion_prj": str(output / "grm2023_testausschnitt.prj"),
			"legende_png": (str(output / "grm2023_legende.png")
				if legend_bytes else None),
		},
		"weitere_pruefung": [
			"Legende und Farbstatistik gegen tatsächliche, möglichst kategoriale Rasterwerte prüfen.",
			"Überlagerungen oder Transparenz/Antialiasing klären, bevor irgendeine RGB-Farbe als Baumschicht klassifiziert wird.",
			"Bei nicht eindeutigem WMS-Renderer amtliche Roh-/Rasterdaten suchen, statt eine Scheinpräzision zu berechnen.",
		],
	}
	(output / "grm2023_wms_diagnose.json").write_text(
		json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	print(f"WMS-Layer: {meta['name']} ({crs})")
	print(f"Raster: {inventory['breite']}×{inventory['hoehe']} px, {inventory['verschiedene_rgba_farben']} Farben")
	print(f"Pixel teils transparent: {inventory['pixel_teiltransparent']}")
	print(f"Legende: {legend_status}")
	print(f"Diagnose: {output / 'grm2023_wms_diagnose.json'}")
	print("Noch keine Baumkronenpolygone erzeugt (Klassenzuordnung offen).")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--fmzk", type=Path, default=DEFAULT_FMZK)
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
	parser.add_argument("--padding-m", type=float, default=10)
	parser.add_argument("--pixel-size-m", type=float, default=0.5)
	args = parser.parse_args()
	try:
		run(fmzk=args.fmzk, output=args.out_dir,
			padding_m=args.padding_m, pixel_size_m=args.pixel_size_m)
	except (OSError, ValueError, TypeError, KeyError, ET.ParseError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
