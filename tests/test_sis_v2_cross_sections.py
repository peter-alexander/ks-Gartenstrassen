"""Unabhängige Geometrietests für den experimentellen Voronoi-Querschnitt."""
import unittest

from shapely.geometry import LineString, Polygon
from scripts.sis_v2_cross_sections import cross_section, detect, evaluate


class CrossSectionTests(unittest.TestCase):
	def test_wedge_detects_first_stable_section(self):
		axis = LineString([(0, 0), (40, 0)])
		polygon = Polygon([(0, 0), (10, -5), (40, -5), (40, 5), (10, 5)])
		result, cross = evaluate(axis, polygon)
		self.assertEqual(result["status"], "grenze_gefunden")
		self.assertAlmostEqual(result["distanz_m"], 10, delta=1)
		self.assertAlmostEqual(cross.length, 10, delta=.001)

	def test_constant_width_has_no_growth(self):
		axis = LineString([(0, 0), (40, 0)])
		polygon = Polygon([(0, -5), (40, -5), (40, 5), (0, 5)])
		result, cross = evaluate(axis, polygon)
		self.assertEqual(result["status"], "keine_stabile_grenze")
		self.assertIsNone(cross)

	def test_cross_section_ignores_separate_parallel_area(self):
		axis = LineString([(0, 0), (30, 0)])
		from shapely.geometry import MultiPolygon
		polygon = MultiPolygon([
			Polygon([(0, -4), (30, -4), (30, 4), (0, 4)]),
			Polygon([(0, 10), (30, 10), (30, 15), (0, 15)]),
		])
		width, _ = cross_section(polygon, axis, 10)
		self.assertAlmostEqual(width, 8)

	def test_no_missing_samples_in_stable_window(self):
		self.assertIsNone(detect([None, (2, None), (4, None), None,
			(10, None), (10, None), (10, None), (10, None)]))


if __name__ == "__main__":
	unittest.main()
