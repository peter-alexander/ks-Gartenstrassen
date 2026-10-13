import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pyproj import Transformer
from shapely.geometry import box, Point, mapping
from shapely.ops import transform

from scripts.build_canopy_circles import (
	diameter_from_properties, parse_trees, merge_trees,
	crowns_from_trees, run as run_circle_provider,
)
from scripts.fetch_vienna_trees import build_wfs_url, validate_result, build_request_bbox
from scripts.measure_canopy_cover import measure_coverage, read_crown_polygons
from scripts.compare_canopy_methods import compare_methods, parse_candidate


class CrownProviderTests(unittest.TestCase):
	def test_diameter_is_strict_and_osm_defaults_explicit(self):
		self.assertEqual(diameter_from_properties(
			{"KRONENDURCHMESSER": "8"}, "wien"), (8, "gemessen_oder_erfasst", "KRONENDURCHMESSER"))
		self.assertEqual(diameter_from_properties({}, "osm")[1], "durchmesser_fehlt")
		self.assertEqual(diameter_from_properties({}, "osm", default_osm_diameter=6),
			(6, "explizit_geschaetzt", "osm_default"))
		self.assertEqual(diameter_from_properties(
			{"KRONENDURCHMESSER": "ca. 10 m"}, "wien")[1], "unlesbarer_durchmesser")
		self.assertEqual(diameter_from_properties(
			{"KRONENDURCHMESSER": "101"}, "wien")[1], "unplausibler_durchmesser")

	def test_osm_rows_and_missing_diameter_excluded(self):
		features = [
			{"type": "Feature", "id": "n1", "geometry": {"type": "Point", "coordinates": [16.36, 48.22]},
				"properties": {"natural": "tree", "diameter_crown": 4}},
			{"type": "Feature", "id": "n2", "geometry": {"type": "Point", "coordinates": [16.361, 48.22]},
				"properties": {"natural": "tree"}},
			{"type": "Feature", "id": "w3", "geometry": {"type": "LineString",
				"coordinates": [[16.36, 48.22], [16.361, 48.22]]},
				"properties": {"natural": "tree_row"}},
		]
		trees, excluded = parse_trees(features, "osm")
		self.assertEqual(len(trees), 1)
		self.assertEqual(excluded, {"baumreihe_ohne_einzelbaumgeometrie": 1, "durchmesser_fehlt": 1})
		estimated, excluded2 = parse_trees(features, "osm", default_osm_diameter=6)
		self.assertEqual(len(estimated), 2)
		self.assertEqual(estimated[1]["diameter_quality"], "explizit_geschaetzt")
		self.assertEqual(excluded2["baumreihe_ohne_einzelbaumgeometrie"], 1)

	def test_dedupe_city_osm_nearby_and_keep_private_tree_crown_over_road(self):
		point = Point(0, 0)
		city = [{"point": point, "provider": "wien", "id": "w1",
			"diameter_m": 12, "diameter_quality": "gemessen_oder_erfasst",
			"diameter_field": "KRONENDURCHMESSER"}]
		osm = [{"point": Point(1, 1), "provider": "osm", "id": "o1",
			"diameter_m": 9, "diameter_quality": "gemessen_oder_erfasst",
			"diameter_field": "diameter_crown"},
			{"point": Point(10, 0), "provider": "osm", "id": "o2",
			"diameter_m": 12, "diameter_quality": "gemessen_oder_erfasst",
			"diameter_field": "diameter_crown"}]
		merged, duplicates = merge_trees(city, osm)
		self.assertEqual([item["id"] for item in merged], ["w1", "o2"])
		self.assertEqual(duplicates[0]["osm_id"], "o1")
		# Stamm außerhalb der Bezugsfläche, Krone greift aber hinein.
		features, _ = crowns_from_trees([city[0]], area_of_interest=box(5, -5, 15, 5))
		self.assertEqual(len(features), 1)
		self.assertEqual(features[0]["geometry"]["type"], "Polygon")

	def test_measure_coverage_union_and_stem_outside(self):
		street = box(0, 0, 10, 10)
		crowns = Point(0, 5).buffer(4).union(Point(8, 5).buffer(4))
		value, part = measure_coverage(street, crowns)
		self.assertGreater(value["ueberschirmt_m2"], 0)
		self.assertLess(value["ueberschirmt_m2"], 100)
		self.assertAlmostEqual(value["ueberschirmt_m2"], part.area)
		self.assertAlmostEqual(value["ueberschirmungsgrad_pct"], value["ueberschirmt_m2"])

	def test_crown_geojson_reader_deduplicates_polygon_features(self):
		x, y = Transformer.from_crs("EPSG:4326", "EPSG:31256", always_xy=True).transform(16.36, 48.22)
		to_lonlat = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform
		polygon = box(x, y, x + 10, y + 10)
		feature = {"type": "Feature", "properties": {},
			"geometry": mapping(transform(to_lonlat, polygon))}
		with tempfile.TemporaryDirectory() as temp:
			file = Path(temp) / "crown.geojson"
			file.write_text(json.dumps({"type": "FeatureCollection", "features": [feature, feature]}))
			geom, meta = read_crown_polygons(file)
			self.assertAlmostEqual(geom.area, 100, delta=0.01)
			self.assertEqual(meta["quell_features"], 2)
			self.assertEqual(len(meta["sha256"]), 64)

	def test_compare_identical_and_disjoint_method_geometries(self):
		street = box(0, 0, 10, 10)
		left = box(0, 0, 5, 10)
		right = box(5, 0, 10, 10)
		metrics, pairs = compare_methods(street, {"wien": left, "monitoring": left})
		self.assertEqual(metrics["wien"]["ueberschirmungsgrad_pct"], 50)
		self.assertEqual(pairs[0]["flaechen_iou"], 1)
		_, pairs2 = compare_methods(street, {"wien": left, "monitoring": right})
		self.assertEqual(pairs2[0]["flaechen_iou"], 0)
		self.assertEqual(pairs2[0]["nur_a_m2"], 50)
		with self.assertRaises(ValueError):
			compare_methods(street, {"wien": left})
		self.assertEqual(parse_candidate("wien=abc.geojson"), ("wien", Path("abc.geojson")))

	def test_wfs_url_has_correct_bbox_and_limit_guards(self):
		bbox = build_request_bbox(box(0, 0, 100, 100), padding_m=35)
		self.assertLess(bbox[0], bbox[2])
		self.assertLess(bbox[1], bbox[3])
		url = build_wfs_url(bbox)
		self.assertIn("BAUMKATOGD", url)
		self.assertIn("EPSG%3A3857", url)
		self.assertIn("maxFeatures=2000", url)
		with self.assertRaisesRegex(ValueError, "maxFeatures"):
			build_wfs_url(bbox, max_features=0)
		to_lonlat = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True).transform
		x, y = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform(16.36, 48.22)
		localbbox = (x - 10, y - 10, x + 10, y + 10)
		data = {"type": "FeatureCollection", "features": [{
			"type": "Feature", "properties": {"KRONENDURCHMESSER": 5},
			"geometry": {"type": "Point", "coordinates": [16.36, 48.22]}
		}]}
		self.assertEqual(validate_result(data, localbbox, max_features=10), 1)
		with self.assertRaisesRegex(ValueError, "Teilmenge"):
			validate_result(data, localbbox, max_features=1)


if __name__ == "__main__":
	unittest.main()
