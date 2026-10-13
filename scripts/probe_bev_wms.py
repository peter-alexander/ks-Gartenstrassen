#!/usr/bin/env python3
"""Methode D, Vorstufe WMS-1: BEV-Orthofoto-Kanaldarstellungen vergleichen.

Der bestehende Kartensammlungs-WMS liefert die fünf Ebenen bev:RGB,
bev:IRGB, bev:RGIR, bev:RIRB und bev:IR als gerenderte PNG-Bilder.
Für dieselbe WMS-1.3.0-EPSG:3857-BBOX und identisches Pixelgitter
werden die Darstellungen gespeichert und ihre redundanten Kanäle geprüft.

WICHTIG: Interne Übereinstimmung beweist keine originalgetreuen
Reflexionswerte! Keine amtlichen NDVI-Werte, keine Kronenmasken.
"""

import argparse
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from PIL import Image, ImageChops, ImageStat
from pyproj import CRS, Transformer
from shapely.ops import transform

from scripts.fmzk_source import load_polygons

WMS_URL = "https://kataster.bev.gv.at/ortho/ows"
WMS_VERSION = "1.3.0"
WMS_CRS = "EPSG:3857"  # Wie in Kartensammlung; 1.3.0-Achsenfolge in 3857 ist x,y.
LAYERS = {
	"rgb": "bev:RGB",
	"irgb": "bev:IRGB",
	"rgir": "bev:RGIR",
	"rirb": "bev:RIRB",
	"ir": "bev:IR",
}
# Erwartete Kanalreplikate: aus den beschrifteten Kartensammlung-WMS-Layern.
CHANNELS = {
	"rot": [("rgb", 0), ("irgb", 1), ("rgir", 0), ("rirb", 0)],
	"gruen": [("rgb", 1), ("irgb", 2), ("rgir", 1)],
	"blau": [("rgb", 2), ("rirb", 2)],
	"nahinfrarot": [("irgb", 0), ("rgir", 2), ("rirb", 1), ("ir", 0)],
	"ir_graustufen": [("ir", 0), ("ir", 1), ("ir", 2)],
}

# Für einen experimentellen Vierkanal-Datensatz reichen die unabhängigen
# Replikate von RGB und IR/RGIR/RIRB. Die zusätzlichen IRGB-R/G-Kanäle
# werden vollständig gemessen, aber getrennt als Darstellungsabweichung
# ausgewiesen. WMS-Anzeigewerte sind keine radiometrischen Rohwerte.
CORE_CHANNELS = {
	"rot": [("rgb", 0), ("rgir", 0), ("rirb", 0)],
	"gruen": [("rgb", 1), ("rgir", 1)],
	"blau": [("rgb", 2), ("rirb", 2)],
	"nahinfrarot": [("ir", 0), ("rgir", 2), ("rirb", 1)],
	"ir_graustufen": [("ir", 0), ("ir", 1), ("ir", 2)],
}
DEFAULT_FMZK = Path("data/processed/fmzk_test.gpkg")
DEFAULT_OUTPUT = Path("data/processed/baumkronen/bev_wms")
MAX_IMAGE_SIDE = 2048
MAX_IMAGE_PIXELS = 3_000_000
MAX_RESPONSE_BYTES = 20_000_000
MIN_VALID_PIXELS = 100
# Rein interne Konsistenzprüfung der gerenderten 8-bit-WMS-Darstellungen.
MAX_MEAN_DIFFERENCE = 0.50
MIN_WITHIN_ONE = 0.995


def local_tag(tag):
	return str(tag).rsplit("}", 1)[-1]


def direct_text(node, name):
	for child in node:
		if local_tag(child.tag) == name and child.text:
			return child.text.strip()
	return None


def parse_capabilities(content):
	if len(content) > MAX_RESPONSE_BYTES:
		raise ValueError("WMS-Capabilities sind zu groß")
	try:
		root = ET.fromstring(content)
	except ET.ParseError as exc:
		raise ValueError("WMS lieferte kein gültiges GetCapabilities-XML") from exc
	if local_tag(root.tag) not in ("WMS_Capabilities", "WMT_MS_Capabilities"):
		raise ValueError("Antwort ist kein WMS-GetCapabilities-Dokument")
	if root.attrib.get("version") != WMS_VERSION:
		raise ValueError("BEV-WMS antwortete mit unerwarteter WMS-Version")
	cap = next((child for child in root if local_tag(child.tag) == "Capability"), None)
	if cap is None:
		raise ValueError("WMS-Capability fehlt")
	request = next((child for child in cap if local_tag(child.tag) == "Request"), None)
	if request is None:
		raise ValueError("WMS-Request-Deklaration fehlt")
	getmap = next((child for child in request if local_tag(child.tag) == "GetMap"), None)
	formats = [child.text.strip().lower() for child in (getmap if getmap is not None else [])
		if local_tag(child.tag) == "Format" and child.text]
	if "image/png" not in formats:
		raise ValueError("WMS bietet kein image/png für GetMap")
	found = {}

	def visit(layer, inherited_crs):
		crs = set(inherited_crs)
		for child in layer:
			if local_tag(child.tag) in ("CRS", "SRS") and child.text:
				crs.update(item.upper() for item in child.text.split())
		name = direct_text(layer, "Name")
		if name in LAYERS.values():
			found[name] = {
				"titel": direct_text(layer, "Title"),
				"crs": sorted(crs),
				"stile": [
					direct_text(style, "Name") for style in layer
					if local_tag(style.tag) == "Style"
				],
			}
		for child in layer:
			if local_tag(child.tag) == "Layer":
				visit(child, crs)

	for child in cap:
		if local_tag(child.tag) == "Layer":
			visit(child, set())
	missing = sorted(set(LAYERS.values()) - found.keys())
	unsupported = sorted(layer for layer, item in found.items()
		if WMS_CRS not in item["crs"])
	# Der BEV-Orthofoto-WMS kann direkt per GetMap erreichbare Layer haben,
	# die im GetCapabilities-Dokument nicht beworben werden. Capabilities
	# dient daher der Dokumentation, nicht als vollständige Positivliste.
	# Erst die fünf realen GetMap-PNG-Antworten entscheiden über Nutzbarkeit.
	return {
		"version": root.attrib["version"],
		"getmap_formate": formats,
		"layer": found,
		"nicht_in_capabilities": missing,
		"epsg3857_nicht_deklariert": unsupported,
		"hinweis": (
			"Nicht deklarierte Layer/CRS sind keine bestätigten GetMap-Fehler. "
			"Direkte GetMap-Anfragen und ihre PNG-Antworten separat prüfen."
		),
	}


def image_geometry(clip, *, padding_m=15, pixel_size_m=0.5):
	if not (0 <= padding_m <= 40):
		raise ValueError("Puffer muss zwischen 0 und 40 m liegen")
	if not (0.25 <= pixel_size_m <= 2):
		raise ValueError("Pixelgröße muss zwischen 0,25 und 2 m liegen")
	roi = clip.buffer(padding_m).envelope
	x0, y0, x1, y1 = roi.bounds
	width = math.ceil((x1 - x0) / pixel_size_m)
	height = math.ceil((y1 - y0) / pixel_size_m)
	if (not 1 <= width <= MAX_IMAGE_SIDE or
		not 1 <= height <= MAX_IMAGE_SIDE or
		width * height > MAX_IMAGE_PIXELS):
		raise ValueError(
			f"Testbild {width}x{height} zu groß; Pixelgröße erhöhen oder Puffer reduzieren")
	project = Transformer.from_crs("EPSG:31256", WMS_CRS, always_xy=True).transform
	bbox = transform(project, roi).bounds
	if not all(math.isfinite(n) for n in bbox) or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
		raise ValueError("WMS-BBOX ungültig")
	return {
		"crs": WMS_CRS, "bbox": list(bbox), "width": width, "height": height,
		"padding_m": padding_m, "ziel_pixelgroesse_am_boden_m_naeherung": pixel_size_m,
		"eigentliches_wms_raster": "EPSG:3857, serverseitig für GetMap gerendert/ggf. resampelt",
		"pixelweite_epsg3857": (bbox[2] - bbox[0]) / width,
		"pixelhoehe_epsg3857": (bbox[3] - bbox[1]) / height,
	}


def wms_url(operation, **params):
	items = {
		"SERVICE": "WMS",
		"VERSION": WMS_VERSION,
		"REQUEST": operation,
		**params,
	}
	return WMS_URL + "?" + urlencode(items)


def get_map_url(layer, geometry):
	return wms_url(
		"GetMap",
		LAYERS=layer, STYLES="",
		CRS=geometry["crs"],
		BBOX=",".join(f"{n:.9f}" for n in geometry["bbox"]),
		WIDTH=geometry["width"], HEIGHT=geometry["height"],
		FORMAT="image/png", TRANSPARENT="TRUE",
	)


def request_bytes(url):
	request = Request(url, headers={
		"User-Agent": "ks-Gartenstrassen/1.0 (BEV WMS orthophoto methodology probe)",
		"Accept": "image/png,application/xml,text/xml,*/*",
	})
	with urlopen(request, timeout=60) as response:
		data = response.read(MAX_RESPONSE_BYTES + 1)
	if len(data) > MAX_RESPONSE_BYTES:
		raise ValueError("BEV-WMS-Antwort überschreitet 20 MB")
	return data


def decode_png(content, expected_size):
	if not content.startswith(b"\x89PNG\r\n\x1a\n"):
		raise ValueError("WMS lieferte keine PNG-Daten, möglicherweise eine ServiceException: "
			+ repr(content[:220]))
	try:
		with Image.open(BytesIO(content)) as src:
			if src.format != "PNG":
				raise ValueError("WMS-Antwort ist kein echtes PNG")
			if src.size != expected_size:
				raise ValueError(f"WMS-Bild {src.size} != erwartetes Pixelgitter {expected_size}")
			if src.width > MAX_IMAGE_SIDE or src.height > MAX_IMAGE_SIDE:
				raise ValueError("WMS-Bild überschreitet Sicherheitsgrenze")
			src.load()
			result = src.convert("RGBA")
	except (OSError, Image.DecompressionBombError) as exc:
		raise ValueError(f"WMS lieferte ungültiges PNG: {exc}") from exc
	return result


def worldfile_parameters(geometry):
	x0, y0, x1, y1 = geometry["bbox"]
	w, h = geometry["width"], geometry["height"]
	px, py = (x1 - x0) / w, -(y1 - y0) / h
	return [px, 0, 0, py, x0 + px / 2, y1 + py / 2]


def full_opaque_mask(images):
	if set(images) != set(LAYERS):
		raise ValueError("Es müssen exakt die fünf BEV-WMS-Bilder vorliegen")
	sizes = {im.size for im in images.values()}
	if len(sizes) != 1:
		raise ValueError("Rasterbilder haben unterschiedliche Abmessungen")
	mask = None
	for im in images.values():
		opaque = im.getchannel("A").point(lambda alpha: 255 if alpha == 255 else 0)
		mask = opaque if mask is None else ImageChops.multiply(mask, opaque)
	return mask



def measure_channel_replicates(images, spec, mask, valid_count):
	"""Statistik für eine fest deklarierte Sammlung von Kanalreplikaten."""
	channels = {}
	comparisons = []
	for name, refs in spec.items():
		first_layer, first_index = refs[0]
		first = images[first_layer].getchannel("RGBA"[first_index])
		group = []
		for layer, channel_index in refs[1:]:
			other = images[layer].getchannel("RGBA"[channel_index])
			diff = ImageChops.difference(first, other)
			hist = diff.histogram(mask)
			compared = sum(hist)
			if compared != valid_count:
				raise ValueError("Inkonsistente Maske bei der Kanalstatistik")
			mean = ImageStat.Stat(diff, mask=mask).mean[0]
			exact_fraction = hist[0] / compared
			within_one_fraction = (hist[0] + hist[1]) / compared
			item = {
				"kanal": name,
				"referenz": f"{first_layer}:RGBA[{first_index}]",
				"vergleich": f"{layer}:RGBA[{channel_index}]",
				"mittelwert_absoluter_unterschied_dn": round(mean, 6),
				"maximaler_unterschied_dn": max((i for i, amount in enumerate(hist) if amount), default=0),
				"anteil_exakt_gleich": round(exact_fraction, 9),
				"anteil_max_1_dn_unterschied": round(within_one_fraction, 9),
				"intern_konsistent": (
					mean <= MAX_MEAN_DIFFERENCE and
					within_one_fraction >= MIN_WITHIN_ONE
				),
			}
			group.append(item)
			comparisons.append(item)
		channels[name] = group
	return channels, comparisons


def compare_channels(images):
	"""Kanalreplikate auf gemeinsamen voll deckenden Pixeln vergleichen."""
	mask = full_opaque_mask(images)
	valid_count = mask.histogram()[255]
	size = next(iter(images.values())).size
	total_count = size[0] * size[1]
	if valid_count < MIN_VALID_PIXELS:
		raise ValueError(f"Zu wenige gemeinsam opake Pixel: {valid_count}")
	channels, comparisons = measure_channel_replicates(
		images, CHANNELS, mask, valid_count)
	core_channels, core_comparisons = measure_channel_replicates(
		images, CORE_CHANNELS, mask, valid_count)
	intern_konsistent = all(item["intern_konsistent"] for item in comparisons)
	core_konsistent = all(item["intern_konsistent"] for item in core_comparisons)
	abweichungen = [item for item in comparisons if not item["intern_konsistent"]]
	caution = (
		"Vergleich ausschließlich zwischen identisch angefragten GERENDERTEN WMS-PNG-Kanälen. "
		"Selbst perfekte Übereinstimmung belegt KEINE unveränderten Rohdatenwerte "
		"und KEINEN wissenschaftlich kalibrierten NDVI."
	)
	visibility = {}
	for layer, im in images.items():
		alpha = im.getchannel("A")
		hist = alpha.histogram()
		visibility[layer] = {
			"gesamt": total_count, "deckend": hist[255],
			"teiltransparent": sum(hist[1:255]), "transparent": hist[0],
		}
	return {
		"pixel_gesamt": total_count,
		"pixel_gemeinsam_deckend": valid_count,
		"pixel_gemeinsam_deckend_anteil": valid_count / total_count,
		"bilder_alpha": visibility,
		"kanalgruppen": channels,
		"alle_kanalreplikate_intern_konsistent": intern_konsistent,
		"kernkanalgruppen": core_channels,
		"kernkanaele_intern_konsistent": core_konsistent,
		"abweichungen_alle_darstellungen": abweichungen,
		"verwendbare_anzeigekanaele": {
			"rot": "bev:RGB / PNG-Kanal R",
			"gruen": "bev:RGB / PNG-Kanal G",
			"blau": "bev:RGB / PNG-Kanal B",
			"nahinfrarot": "bev:IR / PNG-Kanal R (Graustufen)",
		},
		"interpretation_kernkanaele": (
			"Nur die interne Übereinstimmung von RGB+IR mit RGIR/RIRB "
			"ist bestätigt; IRGB-R/G-Unterschiede werden nicht übergangen. "
			"KEIN Nachweis radiometrischer Rohdaten oder kalibrierten NDVI."
		),
		"pruefschwellen": {
			"min_anteil_abweichung_bis_1_dn": MIN_WITHIN_ONE,
			"max_mittlere_abs_abweichung_dn": MAX_MEAN_DIFFERENCE,
		},
		"beweiswert": caution,
		"folgeschritt": (
			"Rohdaten-Farbtransformation und Orthofoto-Aufnahmejahr prüfen; "
			"danach höchstens zunächst experimentelle Vegetationsindizes, "
			"keine automatische Baumkronenmessung."
		),
	}


def run(*, fmzk=DEFAULT_FMZK, output=DEFAULT_OUTPUT,
	padding_m=15, pixel_size_m=0.5, overwrite=False):
	"""Nur einen gleich gerasterten Diagnoselauf, keine impliziten Downloads."""
	output = Path(output)
	files = [output / f"bev_{name}_test.png" for name in LAYERS]
	files += [output / f"bev_{name}_test.pgw" for name in LAYERS]
	files += [output / f"bev_{name}_test.prj" for name in LAYERS]
	files += [output / "getcapabilities.xml", output / "bev_wms_diagnose.json"]
	if any(path.exists() for path in files) and not overwrite:
		raise FileExistsError(
			"BEV-WMS-Diagnose existiert bereits. Vorhandene Daten bewahren; "
			"für einen bewusst neuen Lauf anderen --out-dir oder --overwrite wählen.")
	_, manifest, clip, _ = load_polygons(fmzk)
	geometry = image_geometry(clip, padding_m=padding_m, pixel_size_m=pixel_size_m)
	cap_url = wms_url("GetCapabilities")
	cap_bytes = request_bytes(cap_url)
	capabilities = parse_capabilities(cap_bytes)
	responses = {}
	images = {}
	for alias, layer in LAYERS.items():
		url = get_map_url(layer, geometry)
		try:
			raw = request_bytes(url)
			image = decode_png(raw, (geometry["width"], geometry["height"]))
		except (OSError, ValueError) as exc:
			raise ValueError(
				f"Direkter GetMap-Abruf für {layer} ({alias}) fehlgeschlagen: {exc}"
			) from exc
		responses[alias] = {
			"url": url, "raw": raw,
			"sha256": hashlib.sha256(raw).hexdigest(),
			"status": "getmap_png_valide",
		}
		images[alias] = image
	# Eine leere/gerenderte/uneinheitliche WMS-Darstellung ist ein Prüfresultat
	# und darf nicht stillschweigend in Kronenpolygone umgedeutet werden.
	assessment = compare_channels(images)
	report = {
		"schema_version": 1,
		"created_utc": datetime.now(timezone.utc).isoformat(),
		"phase": "D – BEV WMS Quelle und Kanalkonsistenz; keine Kronenklassifikation",
		"quelle_kartensammlung": "src/app/basemaps/providers/imagery.js",
		"fmzk_geo_package": str(fmzk),
		"testgebiet_bbox_lon_lat": manifest["bbox_lon_lat"],
		"wms": {
			"basis_url": WMS_URL, "version": WMS_VERSION,
			"getcapabilities_url": cap_url,
			"getcapabilities_sha256": hashlib.sha256(cap_bytes).hexdigest(),
			"metadaten": capabilities,
			"bilder": {
				name: {"layer": LAYERS[name],
					"getmap_url": responses[name]["url"],
					"png_sha256": responses[name]["sha256"],
					"status": responses[name]["status"],
					"in_capabilities": LAYERS[name] in capabilities["layer"],
					"datei": str(output / f"bev_{name}_test.png")}
				for name in LAYERS
			},
		},
		"raster_ausrichtung": geometry,
		"vergleich": assessment,
		"aufnahmejahr": "unbekannt; BEV-Bildmetadaten je Abdeckungsbereich prüfen",
		"interpretation": (
			"Rot/NIR können nur als aus WMS-Darstellungen rekonstruierte "
			"8-bit-Anzeigewerte beurteilt werden. Keine radiometrischen "
			"Reflexionsdaten, kein belastbarer NDVI ohne Rohdatenprüfung."
		),
		"outputs": {
			"getcapabilities": str(output / "getcapabilities.xml"),
			"raster_bilder": [str(path) for path in files if path.suffix == ".png"],
			"worldfiles": [str(path) for path in files if path.suffix == ".pgw"],
			"projektion_prj": [str(output / f"bev_{name}_test.prj") for name in LAYERS],
			"bericht": str(output / "bev_wms_diagnose.json"),
		},
	}
	output.mkdir(parents=True, exist_ok=True)
	(output / "getcapabilities.xml").write_bytes(cap_bytes)
	world = "\n".join(f"{v:.12f}" for v in worldfile_parameters(geometry)) + "\n"
	for alias in LAYERS:
		(output / f"bev_{alias}_test.png").write_bytes(responses[alias]["raw"])
		(output / f"bev_{alias}_test.pgw").write_text(world, encoding="ascii")
		(output / f"bev_{alias}_test.prj").write_text(
			CRS.from_user_input(WMS_CRS).to_wkt() + "\n", encoding="utf-8")
	(output / "bev_wms_diagnose.json").write_text(
		json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	if capabilities["nicht_in_capabilities"]:
		print("Hinweis: Nicht in GetCapabilities aufgeführte, aber per GetMap "
			"erfolgreich geprüfte Layer: "
			+ ", ".join(capabilities["nicht_in_capabilities"]))
	if capabilities["epsg3857_nicht_deklariert"]:
		print("Hinweis: EPSG:3857 in Capabilities bei folgenden Layern "
			"nicht deklariert: "
			+ ", ".join(capabilities["epsg3857_nicht_deklariert"]))
	print(f"BEV-WMS: {len(LAYERS)} gleich georeferenzierte GetMap-PNGs, "
		f"{geometry['width']}x{geometry['height']} px (EPSG:3857)")
	print("Gemeinsam deckende Pixel: "
		f"{assessment['pixel_gemeinsam_deckend']}/{assessment['pixel_gesamt']}")
	for name, group in assessment["kanalgruppen"].items():
		print(f"  {name}: " + ", ".join(
			f"{item['vergleich']} {100 * item['anteil_max_1_dn_unterschied']:.2f}% <=1DN"
			for item in group))
	print("Kernkanäle RGB + IR mit unabhängigen WMS-Replikaten: "
		+ ("intern konsistent" if assessment["kernkanaele_intern_konsistent"]
			else "NICHT konsistent"))
	print("Alle fünf Darstellungen einschließlich IRGB-R/G: "
		+ ("intern konsistent" if assessment["alle_kanalreplikate_intern_konsistent"]
			else "Abweichungen vorhanden"))
	if assessment["abweichungen_alle_darstellungen"]:
		for item in assessment["abweichungen_alle_darstellungen"]:
			print("  Hinweis auf Darstellungsabweichung: "
				+ item["kanal"] + " " + item["referenz"] + " vs. "
				+ item["vergleich"] + " (ØΔ="
				+ str(item["mittelwert_absoluter_unterschied_dn"]) + " DN)")
	print(f"Bericht: {output / 'bev_wms_diagnose.json'}")
	print("Keine Kronenflächen, kein NDVI und keine Überschirmungswerte erstellt.")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--fmzk", type=Path, default=DEFAULT_FMZK)
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
	parser.add_argument("--padding-m", type=float, default=15)
	parser.add_argument("--pixel-size-m", type=float, default=0.5)
	parser.add_argument("--overwrite", action="store_true",
		help="Bestehende Diagnose nach expliziter Entscheidung überschreiben")
	args = parser.parse_args()
	try:
		run(fmzk=args.fmzk, output=args.out_dir,
			padding_m=args.padding_m, pixel_size_m=args.pixel_size_m,
			overwrite=args.overwrite)
	except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
