import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from pyproj import CRS
from shapely.geometry import box

from scripts.build_canopy_grm2023 import (
	CATEGORIES,
	TREE_RGB,
	classify_raster,
	polygonize_tree_pixels,
	run,
	validate_source,
)


def write_example(tmp):
	source = Path(tmp)
	png = source / "grm2023_testausschnitt.png"
	legend = source / "grm2023_legende.png"
	world = source / "grm2023_testausschnitt.pgw"
	prj = source / "grm2023_testausschnitt.prj"
	with Image.new("RGBA", (4, 2), (235, 235, 235, 255)) as image:
		# 3 Baum-Pixel bilden ein zusammenhängendes L.
		for x, y in [(0, 0), (1, 0), (1, 1)]:
			image.putpixel((x, y), (*TREE_RGB, 255))
		image.save(png)
	with Image.new("RGB", (4, 2), (255, 255, 255)) as image:
		image.save(legend)
	world.write_text("1\n0\n0\n-1\n0.5\n1.5\n", encoding="ascii")
	prj.write_text(CRS.from_epsg(31256).to_wkt() + "\n", encoding="utf-8")
	sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
	diagnosis = {
		"schema_version": 1,
		"bekannte_fachklasse": {"wert": 3, "bedeutung": "Baumschicht"},
		"wms": {"layer": "GRM2023OGD", "getmap_sha256": sha(png),
			"legende_sha256": sha(legend)},
		"raster_ausrichtung": {"crs": "EPSG:31256",
			"bbox": [0, 0, 4, 2], "width": 4, "height": 2},
		"raster_farbstatistik": {"farben_top": [
			{"rgba": [235, 235, 235, 255], "pixel": 5},
			{"rgba": [56, 168, 0, 255], "pixel": 3},
		]},
	}
	(source / "grm2023_wms_diagnose.json").write_text(
		json.dumps(diagnosis), encoding="utf-8")
	return diagnosis


class GRM2023CanopyProviderTests(unittest.TestCase):
	def test_known_wms_palette_has_nine_disjoint_classes(self):
		self.assertEqual(len(CATEGORIES), 9)
		self.assertEqual(CATEGORIES[TREE_RGB], "Baumschicht")
		self.assertEqual(CATEGORIES[(76, 230, 0)], "Strauchschicht")
		self.assertEqual(CATEGORIES[(211, 255, 190)], "Grasschicht")
		self.assertNotEqual(TREE_RGB, (76, 230, 0))

	def test_exact_raster_colors_and_pixel_area(self):
		pixels = [
			(*TREE_RGB, 255), (*TREE_RGB, 255),
			(235, 235, 235, 255), (235, 235, 235, 255),
			(235, 235, 235, 255), (*TREE_RGB, 255),
			(235, 235, 235, 255), (235, 235, 235, 255),
		]
		polygon, metrics = polygonize_tree_pixels(pixels,
			width=4, height=2, bbox=[0, 0, 4, 2])
		self.assertEqual(metrics["baum_pixel"], 3)
		self.assertEqual(metrics["baum_runs"], 2)
		self.assertAlmostEqual(polygon.area, 3)
		self.assertEqual(metrics["baum_polygon_teilstuecke"], 1)
		self.assertTrue(polygon.covers(box(0, 1, 1, 2)))
		self.assertTrue(polygon.covers(box(1, 0, 2, 1)))
		self.assertAlmostEqual(polygon.intersection(box(0, 0, 2, 2)).area, 3)

	def test_unknown_and_translucent_colors_are_rejected(self):
		for rgba in [(56, 168, 1, 255), (*TREE_RGB, 200), (0, 0, 0, 0)]:
			with self.subTest(rgba=rgba):
				buf = BytesIO()
				with Image.new("RGBA", (2, 1), (235, 235, 235, 255)) as im:
					im.putpixel((0, 0), rgba)
					im.save(buf, format="PNG")
				with self.assertRaisesRegex(ValueError, "unbekannte"):
					classify_raster(buf.getvalue(), width=2, height=1)

	def test_png_frequencies_must_match_diagnosis(self):
		buf = BytesIO()
		with Image.new("RGBA", (2, 1), (*TREE_RGB, 255)) as im:
			im.save(buf, format="PNG")
		with self.assertRaisesRegex(ValueError, "Farbstatistik"):
			classify_raster(buf.getvalue(), width=2, height=1,
				expected_frequencies=[{"rgba": [56, 168, 0, 255], "pixel": 1}])

	def test_realistic_run_writes_geojson_for_unmodified_coverage_module(self):
		with tempfile.TemporaryDirectory() as tmp:
			source = Path(tmp) / "source"
			source.mkdir()
			write_example(source)
			report = run(source=source, output=Path(tmp) / "processed")
			self.assertEqual(report["geometrie"]["baum_pixel"], 3)
			self.assertAlmostEqual(report["geometrie"]["baum_polygon_flaeche_m2"], 3)
			self.assertEqual(report["klassen_pixel"]["Baumschicht"], 3)
			output = Path(report["ausgabe_geojson"])
			self.assertTrue(output.is_file())
			geojson = json.loads(output.read_text(encoding="utf-8"))
			self.assertEqual(geojson["type"], "FeatureCollection")
			self.assertEqual(len(geojson["features"]), 1)
			props = geojson["features"][0]["properties"]
			self.assertEqual(props["source"], "wien_grm2023_wms")
			self.assertEqual(props["pixel_rgb"], "#38A800")
			self.assertEqual(props["original_class"], 3)

	def test_changed_png_or_worldfile_or_crs_is_rejected(self):
		with tempfile.TemporaryDirectory() as tmp:
			source = Path(tmp)
			diag = write_example(source)
			validate_source(diag, source)
			(source / "grm2023_testausschnitt.pgw").write_text(
				"2\n0\n0\n-1\n0.5\n1.5\n", encoding="ascii")
			with self.assertRaisesRegex(ValueError, "Worldfile"):
				validate_source(diag, source)
			(source / "grm2023_testausschnitt.pgw").write_text(
				"1\n0\n0\n-1\n0.5\n1.5\n", encoding="ascii")
			(source / "grm2023_testausschnitt.png").write_bytes(b"not png")
			with self.assertRaisesRegex(ValueError, "SHA-256"):
				validate_source(diag, source)
			diag["raster_ausrichtung"]["crs"] = "EPSG:3857"
			with self.assertRaisesRegex(ValueError, "EPSG:31256"):
				validate_source(diag, source)


if __name__ == "__main__":
	unittest.main()
