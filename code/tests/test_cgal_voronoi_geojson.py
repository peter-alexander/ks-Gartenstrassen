"""Regression checks for CGAL dual geometry before running full Vienna."""
import unittest

from shapely.geometry import LineString, box

from scripts.build_cgal_voronoi_geojson import (
	_polygon_candidates, _record_line)


class CGALFullViennaTests(unittest.TestCase):
	def test_zero_length_draw_fragment_is_not_a_boundary(self):
		self.assertIsNone(_record_line("S",((1.,1.),(1.,1.)),
			box(0,0,10,10)))

	def test_segment_is_clipped_to_city_boundary(self):
		result=_record_line("S",((-10.,5.),(20.,5.)),
			box(0,0,10,10))
		self.assertEqual(result.bounds,(0.,5.,10.,5.))

	def test_polygonization_partitions_complete_rectangle(self):
		window=box(0,0,10,10)
		polygons,stats=_polygon_candidates(
			[LineString([(5,0),(5,10)])],window)
		self.assertEqual(len(polygons),2)
		self.assertAlmostEqual(sum(p.area for p in polygons),100.)
		self.assertLess(stats["gap_m2"],1e-6)

	def test_invalid_ray_direction_raises(self):
		with self.assertRaisesRegex(ValueError,"Vektor"):
			_record_line("R",((5.,5.),(5.,5.)),box(0,0,10,10))


if __name__=="__main__":
	unittest.main()
