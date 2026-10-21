import unittest
from shapely.geometry import box
from scripts.cgal_segment_blocker_witnesses import audit_segment_blocker_witnesses

C={"kind":"S","coordinates":[0,0,0,10000]}
D={"kind":"S","coordinates":[0,10000,10000,10000]}
ROWS=[{"face_index":0,"status":"candidate_only_not_proven","candidate_site":C}]
BOUNDS=[{"face_index":0,"unknown_tile_examples":[
	{"bounds_m":[0,0,2,2],"limiting_site":D}]}]


class SegmentBlockerWitnessTests(unittest.TestCase):
	def test_segment_shared_endpoint_and_no_ownership(self):
		row=audit_segment_blocker_witnesses([box(0,0,2,2)],[None],ROWS,BOUNDS)[0]
		self.assertEqual(row["segment_blocker_samples"][0]["shared_endpoint_count"],1)
		self.assertFalse(row["ownership_proven"])

	def test_distinct_segment_no_shared_endpoint(self):
		bounds=[{"face_index":0,"unknown_tile_examples":[
			{"bounds_m":[0,0,2,2],"limiting_site":{
				"kind":"S","coordinates":[10000,10000,20000,10000]}}]}]
		row=audit_segment_blocker_witnesses([box(0,0,2,2)],[None],ROWS,bounds)[0]
		self.assertEqual(row["segment_blocker_samples"][0]["shared_endpoint_count"],0)

	def test_proven_face_rejected(self):
		with self.assertRaises(ValueError):
			audit_segment_blocker_witnesses([box(0,0,2,2)],[C],ROWS,BOUNDS)

	def test_missing_candidate_rejected(self):
		with self.assertRaises(ValueError):
			audit_segment_blocker_witnesses([box(0,0,2,2)],[None],[],BOUNDS)

	def test_no_samples_is_not_proof(self):
		row=audit_segment_blocker_witnesses([box(0,0,2,2)],[None],ROWS,
			[{"face_index":0,"unknown_tile_examples":[]}])[0]
		self.assertEqual(row["segment_blocker_samples"],[])
		self.assertFalse(row["ownership_proven"])

if __name__=="__main__":
	unittest.main()
