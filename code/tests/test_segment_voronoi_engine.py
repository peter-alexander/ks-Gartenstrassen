import unittest
from shapely.geometry import LineString
from scripts.segment_voronoi_engine import _segments, _noded_segments, construct_segment_diagram

class SegmentVoronoiTests(unittest.TestCase):
	def test_noding_progress_reports_phases(self):
		messages=[]
		segments,_=_noded_segments([
			("a",LineString([(0,0),(10,0)])),
			("b",LineString([(5,-5),(5,5)]))],progress=messages.append)
		self.assertEqual(len(segments),4)
		self.assertTrue(any("Noding (GEOS unary_union): Start" in m
			or "Noding (GEOS unary_union):" in m for m in messages))
		self.assertTrue(any("Segmentzuordnung: fertig" in m for m in messages))

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

	def test_crossing_is_noded_with_owner_assignment(self):
		segments,_=_noded_segments([
			("a",LineString([(0,0),(10,10)])),
			("b",LineString([(0,10),(10,0)]))])
		self.assertEqual(len(segments),4)
		self.assertEqual(list(segments.values()).count("a"),2)
		self.assertEqual(list(segments.values()).count("b"),2)

	def test_short_intermediate_segment_collapses_without_losing_axis(self):
		segments,_=_noded_segments([
			("a",LineString([(0,0),(0.0002,0.0002),(10,0)])),
			("b",LineString([(0,5),(10,5)]))])
		self.assertEqual(len(segments),2)
		self.assertEqual(set(segments.values()),{"a","b"})

	def test_entire_axis_below_grid_still_fails(self):
		with self.assertRaisesRegex(ValueError,"gesamte Achse"):
			_noded_segments([
				("tiny",LineString([(0,0),(0.0002,0.0002)])),
				("normal",LineString([(0,5),(10,5)]))])

	def test_short_vertex_retains_remainder_of_polyline(self):
		segments,_=_noded_segments([
			("a",LineString([(0,0),(10,0),(10.0002,0.0002),(10,10)]))])
		self.assertEqual(len(segments),2)
		self.assertEqual(set(segments.values()),{"a"})

	def test_subgrid_fragment_created_by_noding_is_collapsed(self):
		# Integer-grid segments intersect near a pre-existing endpoint.
		# Their intersection rounds to that endpoint on the 1-mm grid.
		segments,_=_noded_segments([
			("a",LineString([(0,0),(10,10)])),
			("b",LineString([(0,0.001),(0.01,-0.099)]))])
		self.assertIn("a",segments.values())
		self.assertIn("b",segments.values())
		self.assertTrue(all(a!=b for a,b in segments))

	def test_overlapping_different_owners_rejected(self):
		with self.assertRaisesRegex(ValueError,"[Dd]eckungsgleiche|Unklare"):
			_noded_segments([
				("a",LineString([(0,0),(10,0)])),
				("b",LineString([(5,0),(15,0)]))])

if __name__=="__main__":
	unittest.main()
