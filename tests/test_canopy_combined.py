import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pyproj import Transformer
from shapely.geometry import box

from scripts.build_canopy_circles import run as run_a
from scripts.build_canopy_combined import run as run_b
from scripts.canopy_osm_merge import (
	ROW_SPACING_M, PointGrid, metric_point,
	osm_crown_diameter, parse_osm_metres, parse_row_count,
	sample_row, selected_osm_trees,
)
from scripts.fetch_osm_trees import bbox_lonlat, overpass_query, validate_response


TO_WGS = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True)


def lonlat(x, y):
	return TO_WGS.transform(x, y)


def city_feature(identifier, x, y, *, diameter="16-18 m"):
	return {
		"type": "Feature",
		"id": identifier,
		"properties": {
			"BAUM_ID": identifier, "KRONENDURCHMESSER": 7,
			"KRONENDURCHMESSER_TXT": diameter,
		},
		"geometry": {"type": "Point", "coordinates": list(lonlat(x, y))},
	}


def osm_node(identifier, x, y, tags):
	lon, lat = lonlat(x, y)
	return {"type": "node", "id": identifier, "lon": lon, "lat": lat,
		"tags": {"natural": "tree", **tags}}


def osm_row(identifier, points, tags):
	return {"type": "way", "id": identifier, "tags": {"natural": "tree_row", **tags},
		"geometry": [{"lon": lonlat(x, y)[0], "lat": lonlat(x, y)[1]}
			for x, y in points]}


class CombinedCanopyTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.x, cls.y = Transformer.from_crs(
			"EPSG:4326", "EPSG:31256", always_xy=True).transform(16.36, 48.22)

	def features(self):
		x, y = self.x, self.y
		return [
			city_feature("W1", x, y),
			city_feature("W2", x + 80, y, diameter="nicht bekannt"),
		]

	def elements(self):
		x, y = self.x, self.y
		return [
			osm_node(10, x + 1, y, {"diameter_crown": "8 m"}),
			osm_node(11, x + 20, y, {"crown:diameter": "400 cm"}),
			osm_node(12, x + 20.3, y, {"diameter_crown": "5 m"}),
			osm_node(13, x + 100, y, {}),
			osm_node(14, x + 80.5, y, {"diameter_crown": "6 m"}),
			osm_row(20, [(x + 20, y), (x + 60, y)],
				{"tree_count": "3", "height": "10 m"}),
		]

	def test_osm_measurement_and_explicit_solar_fallback(self):
		self.assertAlmostEqual(parse_osm_metres("400 cm"), 4)
		self.assertAlmostEqual(parse_osm_metres("10 ft"), 3.048)
		self.assertAlmostEqual(parse_osm_metres("3500 mm"), 3.5)
		self.assertIsNone(parse_osm_metres("ca. 10m"))
		self.assertIsNone(parse_osm_metres("-1 m"))
		self.assertEqual(osm_crown_diameter({"diameter_crown": "500 cm"}),
			(5.0, "osm_expliziter_kronendurchmesser", "diameter_crown", None))
		self.assertEqual(osm_crown_diameter({"height": "10 m"}),
			(5.0, "solar_geschaetzt_aus_osm_hoehe", "height", 10.0))
		self.assertEqual(osm_crown_diameter({}),
			(6.0, "solar_default_hoehe_12m", None, 12.0))
		self.assertEqual(osm_crown_diameter({}, allow_estimates=False),
			(None, "osm_durchmesser_unbekannt", None, None))

	def test_tree_rows_follow_existing_endpoint_and_midpoint_rules(self):
		x, y = self.x, self.y
		tagged = osm_row(12, [(x + 20, y), (x + 60, y)], {"tree_count": "3"})
		points = sample_row(tagged)
		self.assertEqual(len(points), 3)
		for index, point in enumerate(points):
			self.assertAlmostEqual(point.x, x + 20 + index * 20, delta=0.02)
		default = osm_row(13, [(x + 20, y), (x + 60, y)], {})
		default_points = sample_row(default)
		self.assertEqual(len(default_points), 5)
		self.assertAlmostEqual(default_points[0].x, x + 24, delta=0.02)
		self.assertAlmostEqual(default_points[-1].x, x + 56, delta=0.02)
		self.assertEqual(parse_row_count({}, 40), (5, False))
		self.assertEqual(parse_row_count({"tree_count": "1000"}, 40), (500, True))

	def test_vienna_priority_includes_wien_trees_without_crown_measure(self):
		selected, stats = selected_osm_trees(self.features(),
			{"elements": self.elements()})
		self.assertEqual(stats["osm_nodes_geladen"], 5)
		self.assertEqual(stats["wien_punkte_fuer_dubletten"], 2)
		self.assertEqual(stats["osm_nodes_dublette_wien"], 2)
		self.assertEqual(stats["osm_nodes_dublette_osm"], 1)
		self.assertEqual(stats["osm_reihen_samples_erzeugt"], 3)
		self.assertEqual(stats["osm_reihen_dublette_osm_einzelbaum"], 1)
		self.assertEqual(stats["osm_reihen_samples_nach_merge"], 2)
		self.assertEqual(len(selected), 4)
		self.assertEqual([t["provider"] for t in selected],
			["osm_tree", "osm_tree", "osm_tree_row", "osm_tree_row"])
		self.assertEqual(selected[0]["diameter_m"], 4)
		self.assertEqual(selected[1]["diameter_m"], 6)
		self.assertEqual(selected[2]["diameter_m"], 5)
		self.assertEqual(selected[2]["osm_row_index"], 1)

	def test_strict_osm_retains_merge_but_excludes_missing_diameters(self):
		selected, stats = selected_osm_trees(self.features(),
			{"elements": self.elements()}, allow_estimates=False)
		self.assertEqual(len(selected), 1)
		self.assertEqual(stats["osm_kronendurchmesser_fehlend_strikt"], 3)
		self.assertEqual(selected[0]["id"], "osm:n11")

	def test_osm_json_and_bbox_query_are_validated(self):
		clip = box(self.x - 10, self.y - 10, self.x + 10, self.y + 10)
		bbox = bbox_lonlat(clip, padding_m=35)
		query = overpass_query(bbox)
		self.assertIn('node["natural"="tree"]', query)
		self.assertIn('way["natural"="tree_row"]', query)
		self.assertIn("out body geom qt", query)
		counts = validate_response({"elements": self.elements()})
		self.assertEqual(counts, {"osm_tree": 5, "osm_tree_row": 1})
		with self.assertRaisesRegex(ValueError, "Warnung"):
			validate_response({"elements": self.elements(), "remark": "runtime limit"})
		with self.assertRaisesRegex(ValueError, "doppelte"):
			validate_response({"elements": self.elements() + self.elements()[:1]})

	def test_method_a_explicitly_rejects_osm_inputs(self):
		with self.assertRaisesRegex(ValueError, "Methode B"):
			run_a(wien="baumkataster.geojson", osm="osm.geojson")

	def test_method_b_preserves_city_crowns_and_has_separate_outputs(self):
		x, y = self.x, self.y
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			wien_path = root / "wien.geojson"
			wien_path.write_text(json.dumps({
				"type": "FeatureCollection", "features": self.features()
			}), encoding="utf-8")
			osm_path = root / "osm.json"
			osm_path.write_text(json.dumps({
				"elements": self.elements()
			}), encoding="utf-8")
			fmzk = root / "fmzk.gpkg"
			clip = box(x - 30, y - 40, x + 120, y + 40)
			manifest = {"bbox_lon_lat": [16.35, 48.21, 16.37, 48.23]}
			with patch("scripts.build_canopy_circles.load_polygons",
				return_value=([], manifest, clip, [])):
				report_a = run_a(wien=wien_path, fmzk=fmzk,
					output=root / "a")
			with patch("scripts.build_canopy_combined.load_polygons",
				return_value=([], manifest, clip, [])):
				report_b = run_b(wien=wien_path, osm=osm_path, fmzk=fmzk,
					output=root / "b")
			geo_a = json.loads((root / "a" / "baumkronen_kreise.geojson").read_text())
			geo_b = json.loads((root / "b" / "baumkronen_kombiniert.geojson").read_text())
			self.assertEqual(report_a["baumkronen"], 1)
			self.assertEqual(report_b["quellen_im_ergebnis"],
				{"osm_tree": 2, "osm_tree_row": 2, "wien": 1})
			original = geo_a["features"][0]
			combined = geo_b["features"][0]
			self.assertEqual(original["geometry"], combined["geometry"])
			self.assertEqual(original["properties"]["crown_diameter_m"],
				combined["properties"]["crown_diameter_m"])
			self.assertTrue(geo_b["features"][-1]["properties"]["kronendurchmesser_geschaetzt"])
			self.assertEqual(report_b["merge"]["statistik"]["osm_nodes_dublette_wien"], 2)
			self.assertFalse((root / "a" / "baumkronen_kombiniert.geojson").exists())
			self.assertFalse((root / "b" / "baumkronen_kreise.geojson").exists())


if __name__ == "__main__":
	unittest.main()
