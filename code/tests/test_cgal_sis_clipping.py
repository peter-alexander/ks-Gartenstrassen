"""Regression coverage for vectorized full-Vienna SIS polygon clipping."""
import unittest

from shapely.geometry import box, MultiPolygon

from scripts.build_cgal_voronoi_geojson import _assign


class CGALClippingTests(unittest.TestCase):
	def test_batch_clipping_preserves_ownership_and_area(self):
		owners={
			((0,0),(0,10000)):"left",
			((20000,0),(20000,10000)):"right"}
		polygons=[box(0,0,10,10),box(10,0,20,10)]
		mask=MultiPolygon([box(1,1,9,9),box(11,1,19,9)])
		groups,qa=_assign(polygons,mask,owners,(0,0),batch_size=1)
		self.assertEqual(set(groups),{"left","right"})
		self.assertAlmostEqual(groups["left"].area,64)
		self.assertAlmostEqual(groups["right"].area,64)
		self.assertAlmostEqual(qa["gap_m2"],0)
		self.assertAlmostEqual(qa["overlap_m2"],0)
		self.assertEqual(qa["intersections_calculated"],2)

	def test_one_polygon_multiple_mask_components(self):
		owners={((0,0),(1000,0)):"axis"}
		polygons=[box(-5,-5,5,5)]
		mask=MultiPolygon([box(-4,-4,-2,-2),box(2,2,4,4)])
		groups,qa=_assign(polygons,mask,owners,(0,0),batch_size=2)
		self.assertEqual(set(groups),{"axis"})
		self.assertAlmostEqual(groups["axis"].area,8)
		self.assertEqual(qa["intersections_calculated"],2)

	def test_invalid_batch_size_rejected(self):
		with self.assertRaises(ValueError):
			_assign([],box(0,0,1,1),{},(0,0),batch_size=0)


if __name__=="__main__":
	unittest.main()
