import unittest

from shapely.geometry import box

from scripts.cgal_native_adapter import (
	metric_labelled_segments,reconstruct_native_test_cells)


class NativeAdapterTests(unittest.TestCase):
	def test_native_segment_parabola_fragments_share_generator_pair(self):
		lines=[
			"E 0 P 0 0 | S 1000 0 2000 0",
			"S 0 0 1000 1000",
			"S 1000 1000 2000 2000"]
		result=list(metric_labelled_segments(lines,box(0,0,2,2)))
		self.assertEqual(len(result),2)
		self.assertEqual(result[0][1],result[1][1])
		self.assertAlmostEqual(result[0][0].length,2**.5)

	def test_ray_and_infinite_line_are_window_clipped(self):
		lines=[
			"E 0 P 0 0 | P 1 0",
			"R 0 1000 1000 1000",
			"E 1 P 1 0 | P 2 0",
			"L 1000 1000 1000 2000"]
		result=list(metric_labelled_segments(lines,box(-2,-2,2,2)))
		self.assertEqual(len(result),2)
		self.assertAlmostEqual(result[0][0].length,2)
		self.assertAlmostEqual(result[1][0].length,4)

	def test_native_stream_reconstructs_middle_face(self):
		lines=[
			"E 0 P 0 0 | P 1500 0",
			"S 1000 0 1000 2000",
			"E 1 P 1500 0 | P 3000 0",
			"S 2000 0 2000 2000"]
		polygons,labels,stats=reconstruct_native_test_cells(
			lines,box(0,0,3,2))
		self.assertEqual(stats["proven"],1)
		self.assertEqual(len(polygons),3)

	def test_zero_length_fragments_are_skipped_without_changing_pairs(self):
		lines=[
			"E 0 P 0 0 | P 1000 0",
			"S 1000 0 1000 0",
			"S 1000 -1000 1000 1000"]
		result=list(metric_labelled_segments(lines,box(0,0,2,2)))
		self.assertEqual(len(result),1)
		self.assertAlmostEqual(result[0][0].length,1)


if __name__=="__main__":
	unittest.main()
