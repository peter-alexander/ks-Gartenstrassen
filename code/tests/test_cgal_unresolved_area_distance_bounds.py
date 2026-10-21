import unittest
from shapely.geometry import box
from scripts.cgal_unresolved_area_distance_bounds import audit_unresolved_area_distance_bounds

C=("P",(0,0))
F=("P",(100000,0))
EDGES=[(1,(C,F),[])]
CAND=[{"face_index":0,"status":"candidate_only_not_proven",
	"candidate_site":{"kind":"P","coordinates":[0,0]}}]


class UnresolvedAreaDistanceBoundsTests(unittest.TestCase):
	def test_far_competitor_certifies_entire_rectangle(self):
		row=audit_unresolved_area_distance_bounds([box(-1,-1,1,1)],[None],
			EDGES,CAND,max_depth=2)[0]
		self.assertEqual(row["status"],"full_area_distance_bound_verified_only")
		self.assertAlmostEqual(row["certified_area_m2"],4)
		self.assertFalse(row["ownership_proven"])

	def test_crossing_bisector_remains_unknown(self):
		row=audit_unresolved_area_distance_bounds([box(0,-1,100,1)],[None],
			EDGES,CAND,max_depth=2)[0]
		self.assertEqual(row["status"],"partial_area_distance_bound_unknown")
		self.assertGreater(row["unknown_area_m2"],0)
		self.assertFalse(row["ownership_proven"])

	def test_clipped_polygon_certifies_where_bounding_box_cannot(self):
		from shapely.geometry import Polygon
		# Triangle lies near the candidate, while its bbox contains a far corner.
		poly=Polygon([(0,0),(2,0),(0,2)])
		row=audit_unresolved_area_distance_bounds([poly],[None],
			[(0,(C,("P",(1500,1500))),[])],
			CAND,max_depth=0)[0]
		self.assertEqual(row["status"],"partial_area_distance_bound_unknown")
		# A competitor at (10,10) is far from the clipped triangle.
		row=audit_unresolved_area_distance_bounds([poly],[None],
			[(0,(C,("P",(10000,10000))),[])],
			CAND,max_depth=0)[0]
		self.assertEqual(row["status"],"full_area_distance_bound_verified_only")
		self.assertFalse(row["ownership_proven"])

	def test_proven_face_is_rejected(self):
		with self.assertRaises(ValueError):
			audit_unresolved_area_distance_bounds([box(-1,-1,1,1)],[C],
				EDGES,CAND)

	def test_missing_native_site_is_rejected(self):
		with self.assertRaises(ValueError):
			audit_unresolved_area_distance_bounds([box(-1,-1,1,1)],[None],
				EDGES,[{**CAND[0],"candidate_site":{"kind":"P","coordinates":[4,5]}}])

	def test_no_candidate_never_changes_labels(self):
		labels=[None]
		self.assertEqual(audit_unresolved_area_distance_bounds(
			[box(-1,-1,1,1)],labels,EDGES,[]),[])
		self.assertEqual(labels,[None])

if __name__=="__main__":
	unittest.main()
