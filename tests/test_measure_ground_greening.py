import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pyproj import Transformer
from shapely.geometry import box, mapping
from shapely.ops import transform

from scripts.measure_ground_greening import (
	GREEN_CODES,
	load_street_mask,
	measure_ground_greening,
	run,
)


class GroundGreeningModuleTests(unittest.TestCase):
	def test_numerator_and_denominator_are_both_geometric_unions(self):
		# Eine alternative Straßenraum-Maske hat keine FMZK/Kataster-Attribute.
		street = box(0, 0, 10, 10)
		features = [
			(10, 58, "Grün 58", box(1, 1, 5, 5)),  # 16 m²
			(11, 69, "Grün 69", box(3, 1, 7, 5)),  # 16 m², davon 8 m² überlappt
			(12, 69, "Außerhalb", box(12, 1, 15, 5)),
			(13, 59, "Befestigt", box(1, 1, 7, 5)), # keine Bodenbegrünung
		]
		report, parts = measure_ground_greening(street, features)
		self.assertAlmostEqual(report["strassenraum_flaeche_m2"], 100)
		self.assertAlmostEqual(report["bodenbegruenung_flaeche_m2"], 24)
		self.assertAlmostEqual(report["bodenbegruenungsanteil_pct"], 24)
		self.assertAlmostEqual(report["gruen_flaeche_pro_klasse_m2"]["58"], 16)
		self.assertAlmostEqual(report["gruen_flaeche_pro_klasse_m2"]["69"], 16)
		self.assertAlmostEqual(report["gruen_klassen_ueberlagerung_m2"], 8)
		self.assertEqual(len(parts), 2)
		self.assertEqual(report["fmzk_gruen_features"], 3)

	def test_green_clipped_by_street_mask(self):
		street = box(0, 0, 10, 10)
		report, parts = measure_ground_greening(street, [
			(1, 69, "Grün", box(8, 0, 12, 10)),
			(2, 21, "Fahrbahn", box(0, 0, 8, 10)),
		])
		self.assertAlmostEqual(report["bodenbegruenung_flaeche_m2"], 20)
		self.assertAlmostEqual(report["bodenbegruenungsanteil_pct"], 20)
		self.assertAlmostEqual(parts[0][4].area, 20)
		self.assertAlmostEqual(report["strassenraum_ohne_fmzk_flaechendeckung_m2"], 0)

	def test_no_green_and_mask_not_fully_covered_by_fmzk(self):
		report, parts = measure_ground_greening(box(0, 0, 10, 10), [
			(1, 21, "Fahrbahn", box(0, 0, 5, 10))
		])
		self.assertEqual(report["bodenbegruenung_flaeche_m2"], 0)
		self.assertEqual(report["bodenbegruenungsanteil_pct"], 0)
		self.assertAlmostEqual(report["strassenraum_ohne_fmzk_flaechendeckung_m2"], 50)
		self.assertEqual(parts, [])

	def test_duplicate_source_fid_rejected(self):
		with self.assertRaisesRegex(ValueError, "Doppelte FMZK-FID"):
			measure_ground_greening(box(0, 0, 10, 10), [
				(1, 58, "Grün", box(0, 0, 1, 1)),
				(1, 69, "Grün", box(1, 0, 2, 1)),
			])

	def test_mask_reader_accepts_attribute_free_geojson_and_deduplicates(self):
		to_lonlat = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform
		center = Transformer.from_crs("EPSG:4326", "EPSG:31256", always_xy=True).transform(16.36, 48.22)
		x, y = center
		clip = box(x - 100, y - 100, x + 100, y + 100)
		geom = box(x - 10, y - 10, x + 10, y + 10)
		geo = mapping(transform(to_lonlat, geom))
		with tempfile.TemporaryDirectory() as temp:
			path = Path(temp) / "mask.geojson"
			path.write_text(json.dumps({"type": "FeatureCollection", "features": [
				{"type": "Feature", "geometry": geo, "properties": {}},
				{"type": "Feature", "geometry": geo, "properties": {}},
			]}), encoding="utf-8")
			mask, metadata = load_street_mask(path, clip)
			self.assertAlmostEqual(mask.area, 400, delta=0.001)
			self.assertEqual(metadata["eingabe_features"], 2)
			self.assertEqual(len(metadata["masken_sha256"]), 64)
			self.assertEqual(metadata["reparierte_geometrien"], 0)

	def test_self_intersecting_zero_area_mask_is_repaired(self):
		from shapely.geometry import Polygon
		to_lonlat = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform
		x, y = Transformer.from_crs("EPSG:4326", "EPSG:31256", always_xy=True).transform(16.36, 48.22)
		# Ursprüngliche Shapely-Fläche des Bowtie-Polygons ist 0.
		bowtie = Polygon([(x, y), (x + 10, y + 10), (x + 10, y), (x, y + 10), (x, y)])
		self.assertFalse(bowtie.is_valid)
		self.assertEqual(bowtie.area, 0)
		with tempfile.TemporaryDirectory() as tmp:
			path = Path(tmp) / "mask.geojson"
			path.write_text(json.dumps({"type": "FeatureCollection", "features": [
				{"type": "Feature", "properties": {}, "geometry": mapping(transform(to_lonlat, bowtie))}
			]}))
			mask, metadata = load_street_mask(path, box(x - 10, y - 10, x + 20, y + 20))
			self.assertGreater(mask.area, 0)
			self.assertTrue(mask.is_valid)
			self.assertGreaterEqual(metadata["reparierte_geometrien"], 1)

	def test_unrelated_mask_rejected_not_silently_clipped(self):
		to_lonlat = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform
		center = Transformer.from_crs("EPSG:4326", "EPSG:31256", always_xy=True).transform(16.36, 48.22)
		x, y = center
		geom = box(x + 200, y + 200, x + 210, y + 210)
		with tempfile.TemporaryDirectory() as temp:
			path = Path(temp) / "mask.geojson"
			path.write_text(json.dumps({"type": "FeatureCollection", "features": [
				{"type": "Feature", "geometry": mapping(transform(to_lonlat, geom)), "properties": {}},
			]}), encoding="utf-8")
			with self.assertRaisesRegex(ValueError, "außerhalb des FMZK-Testausschnitts"):
				load_street_mask(path, box(x - 50, y - 50, x + 50, y + 50))

	def test_end_to_end_creates_two_outputs_with_provenance(self):
		to_lonlat = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform
		x, y = Transformer.from_crs("EPSG:4326", "EPSG:31256", always_xy=True).transform(16.36, 48.22)
		clip = box(x - 100, y - 100, x + 100, y + 100)
		mask = box(x, y, x + 10, y + 10)
		features = [
			(1, 21, "Fahrbahn", box(x, y, x + 10, y + 10)),
			(2, 58, "Grün", box(x + 2, y + 2, x + 5, y + 5)),
			(3, 59, "Befestigt", box(x + 5, y + 5, x + 8, y + 8)),
		]
		with tempfile.TemporaryDirectory() as tmp:
			mask_path = Path(tmp) / "strassenraum.geojson"
			mask_path.write_text(json.dumps({"type": "FeatureCollection", "features": [
				{"type": "Feature", "properties": {},
					"geometry": mapping(transform(to_lonlat, mask))}
			]}))
			out = Path(tmp) / "ground"
			with patch("scripts.measure_ground_greening.load_polygons",
				return_value=(features, {"bbox_lon_lat": [16.35, 48.21, 16.37, 48.23]}, clip, [])):
				result = run(mask_path, Path(tmp) / "fmzk.gpkg", out)
			self.assertAlmostEqual(result["kennzahlen"]["bodenbegruenungsanteil_pct"], 9, delta=0.01)
			self.assertEqual(result["schema_version"], 1)
			geo = json.loads((out / "bodenbegruenung_flaechen.geojson").read_text())
			self.assertEqual(len(geo["features"]), 1)
			self.assertEqual(geo["features"][0]["properties"]["fid"], 2)
			on_disk = json.loads((out / "bodenbegruenung_bericht.json").read_text())
			self.assertEqual(on_disk["eingaben"]["strassenraum"]["eingabe_features"], 1)
			self.assertEqual(on_disk["definition"]["gruenklassen_fmzk"], sorted(GREEN_CODES))


if __name__ == "__main__":
	unittest.main()
