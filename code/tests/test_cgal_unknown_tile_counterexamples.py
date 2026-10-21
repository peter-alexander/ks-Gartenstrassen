import unittest
from shapely.geometry import box
from scripts.cgal_unknown_tile_counterexamples import audit_unknown_tile_counterexamples

A=("P",(0,0))
B=("P",(1000,0))
EDGES=[(0,(A,B),[])]
CAND=[{"face_index":0,"status":"candidate_only_not_proven",
	"candidate_site":{"kind":"P","coordinates":[0,0]}}]
BOUNDS=[{"face_index":0,"unknown_tile_examples":[{"bounds_m":[0,0,2,1]}]}]

class UnknownTileCounterexampleTests(unittest.TestCase):
	def test_strict_counterexample_rejects_dominance(self):
		row=audit_unknown_tile_counterexamples([box(0,0,2,1)],[None],
			EDGES,CAND,BOUNDS)[0]
		self.assertEqual(row["status"],"strict_distance_counterexample_found")
		self.assertTrue(row["counterexamples"])
		self.assertFalse(row["ownership_proven"])

	def test_safe_samples_do_not_certify_owner(self):
		row=audit_unknown_tile_counterexamples([box(-2,-1,-1,1)],[None],
			EDGES,CAND,[{"face_index":0,"unknown_tile_examples":[{"bounds_m":[-2,-1,-1,1]}]}])[0]
		self.assertEqual(row["status"],"no_counterexample_in_finite_samples")
		self.assertFalse(row["ownership_proven"])

	def test_proven_face_rejected(self):
		with self.assertRaises(ValueError):
			audit_unknown_tile_counterexamples([box(0,0,2,1)],[A],
				EDGES,CAND,BOUNDS)

	def test_missing_candidate_rejected(self):
		with self.assertRaises(ValueError):
			audit_unknown_tile_counterexamples([box(0,0,2,1)],[None],
				EDGES,[],BOUNDS)

	def test_empty_examples_do_not_certify(self):
		row=audit_unknown_tile_counterexamples([box(0,0,2,1)],[None],
			EDGES,CAND,[{"face_index":0,"unknown_tile_examples":[]}])[0]
		self.assertEqual(row["tested_interior_points"],0)
		self.assertFalse(row["ownership_proven"])

if __name__=="__main__":
	unittest.main()
