import json
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from PIL import Image
from pyproj import Transformer
from shapely.geometry import box

from scripts.probe_bev_wms import (
	CHANNELS, LAYERS, WMS_CRS, WMS_VERSION,
	compare_channels, decode_png, get_map_url, image_geometry,
	parse_capabilities, run, worldfile_parameters,
)

CAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<WMS_Capabilities version="1.3.0" xmlns="http://www.opengis.net/wms">
	<Capability>
		<Request>
			<GetMap><Format>image/png</Format><Format>image/jpeg</Format></GetMap>
		</Request>
		<Layer>
			<Title>BEV Orthofotos</Title><CRS>EPSG:3857</CRS>
			<Layer><Name>bev:RGB</Name><Title>RGB</Title></Layer>
			<Layer><Name>bev:IRGB</Name><Title>IRGB</Title></Layer>
			<Layer><Name>bev:RGIR</Name><Title>RGIR</Title></Layer>
			<Layer><Name>bev:RIRB</Name><Title>RIRB</Title></Layer>
			<Layer><Name>bev:IR</Name><Title>IR</Title></Layer>
		</Layer>
	</Capability>
</WMS_Capabilities>""".encode("utf-8")


def sample_images(size=(18, 12), *, corrupt=None):
	output = {}
	for name in LAYERS:
		image = Image.new("RGBA", size)
		pixels = []
		for y in range(size[1]):
			for x in range(size[0]):
				r = (22 + x * 3 + y) % 255
				g = (35 + x * 4 + y) % 255
				b = (48 + x * 5 + y) % 255
				n = (92 + x * 6 + y) % 255
				components = {
					"rgb": (r, g, b, 255),
					"irgb": (n, r, g, 255),
					"rgir": (r, g, n, 255),
					"rirb": (r, n, b, 255),
					"ir": (n, n, n, 255),
				}
				p = components[name]
				if name == corrupt and x == 0 and y == 0:
					p = (p[0] + 25, p[1], p[2], p[3])
				pixels.append(p)
		image.putdata(pixels)
		output[name] = image
	return output


def to_png(image):
	buffer = BytesIO()
	image.save(buffer, format="PNG")
	return buffer.getvalue()


class BEVWMSProbeTests(unittest.TestCase):
	def test_capabilities_inherits_3857_and_verifies_all_layers(self):
		info = parse_capabilities(CAP_XML)
		self.assertEqual(info["version"], "1.3.0")
		self.assertEqual(set(info["layer"]), set(LAYERS.values()))
		self.assertTrue(all(WMS_CRS in record["crs"]
			for record in info["layer"].values()))

	def test_capabilities_refuses_missing_layer_or_wrong_mime(self):
		with self.assertRaisesRegex(ValueError, "WMS-Layer nicht"):
			parse_capabilities(CAP_XML.replace(b"bev:IR</Name>", b"other</Name>"))
		with self.assertRaisesRegex(ValueError, "kein image/png"):
			parse_capabilities(CAP_XML.replace(b"image/png", b"image/tiff"))
		with self.assertRaisesRegex(ValueError, "kein WMS"):
			parse_capabilities(b"<ServiceExceptionReport/>")
		with self.assertRaisesRegex(ValueError, "Version"):
			parse_capabilities(CAP_XML.replace(b"1.3.0", b"1.1.1"))

	def test_geometry_and_identical_grid_request(self):
		to_m = Transformer.from_crs("EPSG:4326", "EPSG:31256",
			always_xy=True)
		x, y = to_m.transform(16.363, 48.223)
		geometry = image_geometry(box(x - 18, y - 13, x + 18, y + 13),
			padding_m=7, pixel_size_m=0.5)
		self.assertEqual((geometry["width"], geometry["height"]), (100, 80))
		queries = [parse_qs(urlparse(get_map_url(layer, geometry)).query)
			for layer in LAYERS.values()]
		self.assertEqual({q["BBOX"][0] for q in queries}.__len__(), 1)
		self.assertEqual({q["CRS"][0] for q in queries}, {"EPSG:3857"})
		self.assertEqual({q["WIDTH"][0] for q in queries}, {"100"})
		self.assertEqual({q["HEIGHT"][0] for q in queries}, {"80"})
		self.assertEqual({q["LAYERS"][0] for q in queries}, set(LAYERS.values()))
		self.assertEqual({q["VERSION"][0] for q in queries}, {WMS_VERSION})
		self.assertEqual(worldfile_parameters(geometry)[0],
			(geometry["bbox"][2] - geometry["bbox"][0]) / 100)
		with self.assertRaisesRegex(ValueError, "zu groß"):
			image_geometry(box(x, y, x+2500, y+2500), pixel_size_m=0.25)

	def test_replicated_rgb_nir_channels_are_compared(self):
		images = sample_images()
		result = compare_channels(images)
		self.assertTrue(result["alle_kanalreplikate_intern_konsistent"])
		self.assertEqual(result["pixel_gemeinsam_deckend"], 216)
		self.assertEqual(len(result["kanalgruppen"]["rot"]), 3)
		self.assertEqual(len(result["kanalgruppen"]["nahinfrarot"]), 3)
		self.assertEqual(len(result["kanalgruppen"]["ir_graustufen"]), 2)
		self.assertTrue(all(x["anteil_exakt_gleich"] == 1
			for group in result["kanalgruppen"].values() for x in group))
		self.assertIn("KEINE unveränderten", result["beweiswert"])

	def test_rendering_difference_makes_gate_fail(self):
		images = sample_images((100, 100))
		images["ir"].putpixel((3, 5), (0, 0, 0, 255))
		difference = compare_channels(images)
		# One mismatched pixel among 10,000 remains within conservative tolerance.
		self.assertTrue(difference["alle_kanalreplikate_intern_konsistent"])
		for y in range(100):
			for x in range(100):
				p = images["ir"].getpixel((x, y))
				images["ir"].putpixel((x, y),
					((p[0] + 25) % 256,) * 3 + (255,))
		difference = compare_channels(images)
		self.assertFalse(difference["alle_kanalreplikate_intern_konsistent"])
		self.assertLess(
			difference["kanalgruppen"]["nahinfrarot"][-1]["anteil_exakt_gleich"], 0.01)

	def test_transparency_counts_and_empty_masks_are_rejected(self):
		images = sample_images()
		images["rgb"].putpixel((0, 0), (0, 0, 0, 0))
		r = compare_channels(images)
		self.assertEqual(r["pixel_gemeinsam_deckend"], 215)
		self.assertEqual(r["bilder_alpha"]["rgb"]["transparent"], 1)
		images["rgb"].putalpha(0)
		with self.assertRaisesRegex(ValueError, "Zu wenige"):
			compare_channels(images)

	def test_png_validation_excludes_xml_and_wrong_image_grid(self):
		with self.assertRaisesRegex(ValueError, "keine PNG"):
			decode_png(b"<ServiceExceptionReport/>", (10, 10))
		with self.assertRaisesRegex(ValueError, "erwartetes Pixelgitter"):
			decode_png(to_png(sample_images((18, 12))["rgb"]), (1, 1))

	def test_full_diagnostic_writes_five_georeferenced_images_no_crowns(self):
		to_m = Transformer.from_crs("EPSG:4326", "EPSG:31256",
			always_xy=True)
		x, y = to_m.transform(16.363, 48.223)
		clip = box(x-14, y-10, x+14, y+10)
		with tempfile.TemporaryDirectory() as tmp:
			target = Path(tmp) / "wms"
			def fake_request(url):
				q = parse_qs(urlparse(url).query)
				if q["REQUEST"] == ["GetCapabilities"]:
					return CAP_XML
				if q["REQUEST"] != ["GetMap"]:
					raise AssertionError(url)
				alias = {layer: name for name, layer in LAYERS.items()}[q["LAYERS"][0]]
				img = sample_images((int(q["WIDTH"][0]), int(q["HEIGHT"][0])))
				return to_png(img[alias])
			with patch("scripts.probe_bev_wms.load_polygons",
				return_value=([], {"bbox_lon_lat": [16.36, 48.22, 16.37, 48.23]}, clip, [])), patch(
				"scripts.probe_bev_wms.request_bytes", side_effect=fake_request):
				report = run(output=target, pixel_size_m=1, padding_m=0)
			self.assertTrue(report["vergleich"]["alle_kanalreplikate_intern_konsistent"])
			for name in LAYERS:
				self.assertTrue((target / f"bev_{name}_test.png").exists())
				self.assertTrue((target / f"bev_{name}_test.pgw").exists())
			self.assertTrue((target / "bev_test.prj").exists())
			self.assertTrue((target / "bev_wms_diagnose.json").exists())
			self.assertEqual(report["aufnahmejahr"], "unbekannt; BEV-Bildmetadaten je Abdeckungsbereich prüfen")
			self.assertFalse(any(target.rglob("*.geojson")))
			with patch("scripts.probe_bev_wms.load_polygons") as mocked_load:
				with self.assertRaises(FileExistsError):
					run(output=target)
				mocked_load.assert_not_called()


if __name__ == "__main__":
	unittest.main()
