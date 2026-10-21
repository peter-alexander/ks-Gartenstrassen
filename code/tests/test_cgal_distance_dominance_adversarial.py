import unittest
from shapely.geometry import Point,box
from scripts.cgal_unresolved_area_distance_bounds import (
	_parallel_segment_projection_dominance,
	_shared_endpoint_affine_distance_dominance,
	_shared_endpoint_behind_halfplane,
	audit_unresolved_area_distance_bounds,
)

def corners(poly):
	return [Point(xy) for xy in poly.exterior.coords]

def segment(a,b):
	return ("S",(*a,*b))

class AdversarialDistanceDominanceTests(unittest.TestCase):
	def test_parallel_projection_outside_segment_rejected(self):
		a=segment((0,0),(0,10000))
		b=segment((10000,0),(10000,10000))
		self.assertFalse(_parallel_segment_projection_dominance(
			a,b,corners(box(1,11,2,12)),1000,1e-9))

	def test_parallel_distance_order_reversed_rejected(self):
		a=segment((0,0),(0,10000))
		b=segment((10000,0),(10000,10000))
		self.assertFalse(_parallel_segment_projection_dominance(
			a,b,corners(box(8,1,9,2)),1000,1e-9))

	def test_parallel_crossing_signed_distance_rejected(self):
		a=segment((0,0),(0,10000))
		b=segment((10000,0),(10000,10000))
		self.assertFalse(_parallel_segment_projection_dominance(
			a,b,corners(box(-1,1,1,2)),1000,1e-9))

	def test_shared_endpoint_projection_outside_rejected(self):
		a=segment((0,0),(0,10000))
		b=segment((0,10000),(10000,10000))
		self.assertFalse(_shared_endpoint_affine_distance_dominance(
			a,b,corners(box(-1,1,-.5,2)),1000,1e-9))

	def test_shared_endpoint_rear_halfplane_rejects_forward(self):
		a=segment((0,0),(0,10000))
		b=segment((0,10000),(10000,10000))
		self.assertFalse(_shared_endpoint_behind_halfplane(
			a,b,corners(box(1,8,2,9)),1000))

	def test_full_area_not_promoted_when_competitor_is_closer(self):
		a=segment((0,0),(0,10000))
		b=segment((10000,0),(10000,10000))
		candidate=[{"face_index":0,"status":"candidate_only_not_proven",
			"candidate_site":{"kind":"S","coordinates":list(a[1])}}]
		poly=box(8,1,9,2)
		row=audit_unresolved_area_distance_bounds([poly],[None],
			[(0,(a,b),[])],candidate,max_depth=0)[0]
		self.assertEqual(row["status"],"partial_area_distance_bound_unknown")
		self.assertGreater(row["unknown_area_m2"],0)
		self.assertFalse(row["ownership_proven"])

if __name__=="__main__":
	unittest.main()
