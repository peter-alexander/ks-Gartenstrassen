import unittest
from shapely.geometry import LineString
from scripts.segment_voronoi_engine import _segments, construct_segment_diagram

class SegmentVoronoiTests(unittest.TestCase):
	def test_polyline_sites(self):
		segs=_segments([("a",LineString([(0,0),(10,0),(10,10)]))])
		self.assertEqual(len(segs),2)

	def test_parallel_segment_sites(self):
		try:
			import pyvoronoi
		except ImportError:
			self.skipTest("pyvoronoi unavailable")
		diagram,owners=construct_segment_diagram([
			("a",LineString([(0,0),(100,0)])),
			("b",LineString([(0,20),(100,20)]))])
		self.assertEqual(set(owners),{"a","b"})
		self.assertTrue(diagram.GetCells())

	def test_crossings_do_not_silently_pass(self):
		with self.assertRaisesRegex(ValueError,"Segmentkreuzung"):
			construct_segment_diagram([
				("a",LineString([(0,0),(10,10)])),
				("b",LineString([(0,10),(10,0)]))])

if __name__=="__main__":
	unittest.main()
