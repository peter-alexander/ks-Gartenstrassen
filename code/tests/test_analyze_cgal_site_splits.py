"""Analyze saved native sites; do not silently relabel polygon interiors."""
import unittest
from shapely.geometry import LineString,box
from scripts.analyze_cgal_site_splits import analyze


class NativeSiteSplitAnalysisTests(unittest.TestCase):
	def test_genuine_split_over_two_polygon_interiors(self):
		faces=[box(0,0,5,10),box(5,0,10,10)]
		sites=[(41,"original-a",LineString([(1,5),(9,5)]))]
		result=analyze(faces,sites,box(0,0,10,10))
		self.assertEqual(result["interior_faces_per_site"],{"2":1})
		self.assertEqual(result["distinct_segment_edge_ids_per_polygon"],
			{"1":2})
		self.assertEqual(result["sum_of_interior_lengths_vs_clipped_site"],
			{"summed_interior_length_99_101pct":1})
		self.assertEqual(result["site_examples"][0]["interior_face_count"],2)
		self.assertEqual(result["site_examples"][0][
			"secondary_interior_fraction"],.5)
		self.assertFalse(result["edge_ids_assigned"])
		self.assertFalse(result["point_sites_processed"])

	def test_tiny_secondary_interior_share_is_reported_not_suppressed(self):
		faces=[box(0,0,9.999,10),box(9.999,0,10,10)]
		sites=[(8,"original-a",LineString([(0,5),(10,5)]))]
		result=analyze(faces,sites,box(0,0,10,10))
		self.assertEqual(result["interior_faces_per_site"],{"2":1})
		self.assertEqual(result["second_largest_site_piece_fraction"],
			{"<25%":1})

	def test_distinct_edge_ids_touching_same_face_are_counted(self):
		faces=[box(0,0,10,10),box(12,0,22,10)]
		sites=[
			(1,"a",LineString([(1,2),(5,2)])),
			(2,"b",LineString([(1,8),(5,8)])),
			(3,"out",LineString([(30,4),(40,4)]))]
		result=analyze(faces,sites,box(0,0,22,10))
		self.assertEqual(result["distinct_segment_edge_ids_per_polygon"],
			{"2+":1,"0":1})
		self.assertEqual(result["interior_faces_per_site"],
			{"1":2,"outside_window":1})
		self.assertEqual(result["site_examples"],[])

	def test_boundary_only_contact_is_not_interior(self):
		faces=[box(0,0,10,10),box(10,0,20,10)]
		sites=[(10,"a",LineString([(10,2),(10,8)]))]
		result=analyze(faces,sites,box(0,0,20,10))
		self.assertEqual(result["interior_faces_per_site"],{"0":1})
		self.assertEqual(result["distinct_segment_edge_ids_per_polygon"],
			{"0":2})


if __name__=="__main__":
	unittest.main()
