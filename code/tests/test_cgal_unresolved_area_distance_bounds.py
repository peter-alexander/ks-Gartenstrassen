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

	def test_unknown_tile_reports_limiting_native_site(self):
		row=audit_unresolved_area_distance_bounds([box(0,-1,100,1)],[None],
			EDGES,CAND,max_depth=1)[0]
		self.assertGreater(row["unknown_area_m2"],0)
		self.assertTrue(row["unknown_tile_examples"])
		self.assertEqual(row["unknown_tile_examples"][0]["limiting_site"],
			{"kind":"P","coordinates":[100000,0]})
		self.assertAlmostEqual(sum(x["area_m2"] for x in
			row["unknown_area_by_limiting_site"]),row["unknown_area_m2"])
		self.assertFalse(row["ownership_proven"])

	def test_limited_samples_keep_full_area_aggregation(self):
		row=audit_unresolved_area_distance_bounds([box(0,-1,100,1)],[None],
			EDGES,CAND,max_depth=2,diagnostic_limit=1)[0]
		self.assertEqual(len(row["unknown_tile_examples"]),1)
		self.assertAlmostEqual(sum(x["area_m2"] for x in
			row["unknown_area_by_limiting_site"]),row["unknown_area_m2"])

	def test_segment_endpoint_points_do_not_block_distance_bound(self):
		segment=("S",(0,0,0,10000))
		endpoint=("P",(0,0))
		other=("P",(100000,100000))
		candidate=[{"face_index":0,"status":"candidate_only_not_proven",
			"candidate_site":{"kind":"S","coordinates":[0,0,0,10000]}}]
		row=audit_unresolved_area_distance_bounds([box(-1,1,1,9)],[None],
			[(1,(segment,endpoint),[]),(2,(segment,other),[])],
			candidate,max_depth=0)[0]
		self.assertEqual(row["status"],"full_area_distance_bound_verified_only")
		self.assertEqual(row["generator_count"],3)
		self.assertEqual(row["non_strict_dominated_sites"],
			[{"kind":"P","coordinates":[0,0]}])
		self.assertFalse(row["ownership_proven"])

	def test_noncollinear_point_is_not_dominated(self):
		segment=("S",(0,0,0,10000))
		point=("P",(1000,0))
		candidate=[{"face_index":0,"status":"candidate_only_not_proven",
			"candidate_site":{"kind":"S","coordinates":[0,0,0,10000]}}]
		row=audit_unresolved_area_distance_bounds([box(-1,1,1,9)],[None],
			[(1,(segment,point),[])],candidate,max_depth=0)[0]
		self.assertEqual(row["non_strict_dominated_site_count"],0)
		self.assertFalse(row["ownership_proven"])

	def test_shared_endpoint_behind_halfplane_certifies_tile(self):
		candidate=("S",(0,0,0,10000))
		competitor=("S",(0,0,10000,0))
		rows=[{"face_index":0,"status":"candidate_only_not_proven",
			"candidate_site":{"kind":"S","coordinates":[0,0,0,10000]}}]
		result=audit_unresolved_area_distance_bounds([box(-2,1,-1,2)],[None],
			[(0,(candidate,competitor),[])],rows,max_depth=0)[0]
		self.assertEqual(result["status"],"full_area_distance_bound_verified_only")
		self.assertAlmostEqual(result["shared_endpoint_halfplane_covered_area_m2"],1)
		self.assertFalse(result["ownership_proven"])

	def test_shared_endpoint_forward_projection_does_not_certify(self):
		candidate=("S",(0,0,0,10000))
		competitor=("S",(0,0,10000,0))
		rows=[{"face_index":0,"status":"candidate_only_not_proven",
			"candidate_site":{"kind":"S","coordinates":[0,0,0,10000]}}]
		result=audit_unresolved_area_distance_bounds([box(1,1,2,2)],[None],
			[(0,(candidate,competitor),[])],rows,max_depth=0)[0]
		self.assertEqual(result["shared_endpoint_halfplane_covered_area_m2"],0)
		self.assertFalse(result["ownership_proven"])

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
