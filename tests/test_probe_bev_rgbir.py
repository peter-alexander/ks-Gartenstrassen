import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pyproj import CRS
from shapely.geometry import box

from scripts.probe_bev_rgbir import (
	clip_geometry, inspect_dataset, run, validate_coverage,
)


def fake_gdal_info(bands=4, *, crs="EPSG:31256", gt=None):
	return {
		"driverShortName": "GTiff",
		"size": [8000, 8000],
		"geoTransform": gt or [1500, 0.2, 0, 343200, 0, -0.2],
		"coordinateSystem": ({"wkt": CRS.from_user_input(crs).to_wkt()}
			if crs is not None else {}),
		"bands": [
			{"band": i + 1, "colorInterpretation": ["Red", "Green", "Blue", "Undefined"][i]
				if i < 4 else "Undefined", "type": "Byte"}
			for i in range(bands)
		],
	}


class BEVRGBIRDiagnosticsTests(unittest.TestCase):
	def test_four_band_file_metadata_without_inventing_nir_mapping(self):
		data, footprint = inspect_dataset(fake_gdal_info(4))
		self.assertEqual(data["crs_epsg"], 31256)
		self.assertEqual(data["band_count"], 4)
		self.assertEqual([b["color_interpretation"] for b in data["bands"]],
			["Red", "Green", "Blue", "Undefined"])
		self.assertAlmostEqual(footprint.area, 8000 * 8000 * .04)

	def test_three_plus_one_band_files_separately(self):
		rgb, rgb_footprint = inspect_dataset(fake_gdal_info(3),
			required_bands=3)
		nir, nir_footprint = inspect_dataset(fake_gdal_info(1),
			required_bands=1)
		self.assertEqual(rgb["band_count"], 3)
		self.assertEqual(nir["band_count"], 1)
		self.assertTrue(rgb_footprint.equals(nir_footprint))

	def test_rgbi_requires_four_bands_and_georeferencing(self):
		with self.assertRaisesRegex(ValueError, "Erwartet 4 Rasterbänder"):
			inspect_dataset(fake_gdal_info(3))
		data = fake_gdal_info(4)
		del data["geoTransform"]
		with self.assertRaisesRegex(ValueError, "Georeferenzierung"):
			inspect_dataset(data)
		data = fake_gdal_info(4, crs=None)
		with self.assertRaisesRegex(ValueError, "Quellprojektion"):
			inspect_dataset(data)
		result, _ = inspect_dataset(data, source_crs="EPSG:31256")
		self.assertTrue(result["source_crs_explicit"])
		with self.assertRaisesRegex(ValueError, "widerspricht"):
			inspect_dataset(fake_gdal_info(4), source_crs="EPSG:3857")

	def test_small_test_area_is_limited_and_source_must_cover(self):
		data, footprint = inspect_dataset(fake_gdal_info(4))
		bbox, size = clip_geometry(box(2000, 342800, 2400, 343100), padding_m=10)
		self.assertLessEqual(size[0] * size[1], 12_000_000)
		self.assertTrue(validate_coverage(footprint, bbox))
		with self.assertRaisesRegex(ValueError, "nicht vollständig"):
			validate_coverage(footprint, [0, 0, 100, 100])
		with self.assertRaisesRegex(ValueError, "zu groß"):
			clip_geometry(box(0, 0, 3000, 3000))

	def test_single_four_band_file_metadata_only(self):
		with tempfile.TemporaryDirectory() as tmp:
			source = Path(tmp) / "bev_rgbir.tif"
			source.write_bytes(b"synthetic not read by GDAL mock")
			out = Path(tmp) / "result"
			with patch("scripts.probe_bev_rgbir.gdal_info",
				return_value=fake_gdal_info(4)):
				report = run(source=source, output=out)
			self.assertEqual(report["quellenmodus"], "einzelnes_rgbir_tiff")
			self.assertIsNone(report["quelle_aufnahmejahr_nach_manueller_pruefung"])
			self.assertFalse(report["grafik_kanaele_bestaetigt"])
			self.assertNotIn("clip", report)
			self.assertTrue((out / "bev_rgbir_diagnose.json").is_file())

	def test_separate_rgb_and_nir_files_metadata_only(self):
		with tempfile.TemporaryDirectory() as tmp:
			rgb = Path(tmp) / "rgb.tif"
			nir = Path(tmp) / "nir.tif"
			rgb.write_bytes(b"rgb")
			nir.write_bytes(b"nir")
			with patch("scripts.probe_bev_rgbir.gdal_info",
				side_effect=[fake_gdal_info(3), fake_gdal_info(1)]):
				report = run(source=rgb, nir_source=nir,
					output=Path(tmp) / "result", acquisition_year=2025)
			self.assertEqual(report["quellenmodus"], "getrennte_rgb_nir_tiffs")
			self.assertEqual(report["nir_datensatz"]["band_count"], 1)
			self.assertEqual(report["quelle_aufnahmejahr_nach_manueller_pruefung"], 2025)
			self.assertFalse(report["grafik_kanaele_bestaetigt"])


if __name__ == "__main__":
	unittest.main()
