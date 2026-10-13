import json
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from PIL import Image
from shapely.geometry import box

from scripts.probe_grm2023_wms import (
	choose_srs,
	get_map_url,
	image_request_geometry,
	parse_capabilities,
	raster_inventory,
	require_png,
	run,
)

CAPABILITIES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<WMT_MS_Capabilities version="1.1.1">
	<Service><Name>OGC:WMS</Name></Service>
	<Capability>
		<Request>
			<GetMap><Format>image/png</Format><Format>image/jpeg</Format></GetMap>
			<GetLegendGraphic><Format>image/png</Format></GetLegendGraphic>
		</Request>
		<Layer>
			<Title>Stadt Wien</Title>
			<SRS>EPSG:3857</SRS>
			<Layer>
				<Name>GRM2023OGD</Name>
				<Title>Grünraummonitoring 2023</Title>
				<SRS>EPSG:31256</SRS>
				<Style><Name>default</Name><Title>Normaldarstellung</Title></Style>
			</Layer>
		</Layer>
	</Capability>
</WMT_MS_Capabilities>""".encode("utf-8")


def png_data(size=(8, 8), *, rgba=(0, 145, 30, 255)):
	stream = BytesIO()
	with Image.new("RGBA", size, rgba) as im:
		im.save(stream, format="PNG")
	return stream.getvalue()


class GRM2023ProbeTest(unittest.TestCase):
	def test_capabilities_resolves_layer_and_inherits_coordinate_system(self):
		metadata = parse_capabilities(CAPABILITIES_XML)
		self.assertEqual(metadata["name"], "GRM2023OGD")
		self.assertEqual(metadata["title"], "Grünraummonitoring 2023")
		self.assertEqual(metadata["unterstuetzte_srs"],
			["EPSG:31256", "EPSG:3857"])
		self.assertEqual(choose_srs(metadata), "EPSG:31256")
		self.assertEqual(metadata["stile"][0]["name"], "default")

	def test_capabilities_refuses_unknown_layer_or_missing_png(self):
		with self.assertRaisesRegex(ValueError, "nicht in GetCapabilities"):
			parse_capabilities(CAPABILITIES_XML, layer="WRONG_LAYER")
		xml = CAPABILITIES_XML.replace(b"image/png", b"image/gif")
		with self.assertRaisesRegex(ValueError, "kein image/png"):
			parse_capabilities(xml)
		with self.assertRaisesRegex(ValueError, "kein WMS"):
			parse_capabilities(b"<ServiceExceptionReport></ServiceExceptionReport>")

	def test_bbox_and_png_dimensions_are_bounded_and_metric(self):
		clip = box(1000, 3000, 1040, 3020)
		spec = image_request_geometry(clip, "EPSG:31256",
			padding_m=10, pixel_size_m=0.5)
		self.assertEqual(spec["bbox"], [990.0, 2990.0, 1050.0, 3030.0])
		self.assertEqual((spec["width"], spec["height"]), (120, 80))
		query = parse_qs(urlparse(get_map_url(spec)).query)
		self.assertEqual(query["layers"], ["GRM2023OGD"])
		self.assertEqual(query["srs"], ["EPSG:31256"])
		self.assertEqual(query["format"], ["image/png"])
		self.assertEqual(query["width"], ["120"])
		with self.assertRaisesRegex(ValueError, "zu groß"):
			image_request_geometry(box(0, 0, 3000, 3000),
				"EPSG:31256", pixel_size_m=0.5)
		self.assertEqual(choose_srs({"unterstuetzte_srs": ["EPSG:3857"]}),
			"EPSG:3857")

	def test_raster_inventory_preserves_rgba_and_does_not_assign_tree_class(self):
		binary = png_data()
		self.assertEqual(require_png(binary, expected_size=(8, 8)), (8, 8))
		stats = raster_inventory(binary)
		self.assertEqual(stats["pixel_gesamt"], 64)
		self.assertEqual(stats["verschiedene_rgba_farben"], 1)
		self.assertEqual(stats["farben_top"][0]["hex_rgb"], "#00911E")
		self.assertEqual(stats["farben_top"][0]["pixel"], 64)
		self.assertEqual(stats["pixel_opaque"], 64)
		self.assertNotIn("baum", stats)
		with self.assertRaisesRegex(ValueError, "keine PNG"):
			require_png(b"<ServiceExceptionReport>bad</ServiceExceptionReport>")
		with self.assertRaisesRegex(ValueError, "≠ angefragte"):
			require_png(binary, expected_size=(10, 10))

	def test_diagnose_e2e_writes_no_crowns_or_false_classification(self):
		clip = box(1000, 3000, 1040, 3020)
		with tempfile.TemporaryDirectory() as tmp:
			out = Path(tmp) / "grm"
			def fake_response(url, *, limit=None):
				query = parse_qs(urlparse(url).query)
				request = query["request"][0]
				if request == "GetCapabilities":
					return CAPABILITIES_XML
				if request == "GetMap":
					return png_data((int(query["width"][0]), int(query["height"][0])))
				if request == "GetLegendGraphic":
					return png_data()
				raise AssertionError("Unexpected request " + url)
			with patch("scripts.probe_grm2023_wms.load_polygons",
				return_value=([], {"bbox_lon_lat": [16.36, 48.22, 16.37, 48.23]}, clip, [])), patch(
				"scripts.probe_grm2023_wms.request_bytes",
				side_effect=fake_response):
				report = run(fmzk=Path(tmp) / "fmzk.gpkg", output=out)
			self.assertEqual(report["wms"]["layer"], "GRM2023OGD")
			self.assertEqual(report["raster_ausrichtung"]["crs"], "EPSG:31256")
			self.assertEqual(report["raster_farbstatistik"]["pixel_gesamt"], 120 * 80)
			self.assertTrue((out / "getcapabilities.xml").is_file())
			self.assertTrue((out / "grm2023_testausschnitt.png").is_file())
			self.assertTrue((out / "grm2023_legende.png").is_file())
			self.assertTrue((out / "grm2023_wms_diagnose.json").is_file())
			self.assertFalse((out / "baumkronen.geojson").exists())
			self.assertIn("keine validierte", json.loads(
				(out / "grm2023_wms_diagnose.json").read_text())["status"])


if __name__ == "__main__":
	unittest.main()
