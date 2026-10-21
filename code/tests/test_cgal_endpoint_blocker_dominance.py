import unittest
from scripts.cgal_endpoint_blocker_dominance import audit_endpoint_blocker_dominance

C=[{"face_index":1,"status":"candidate_only_not_proven",
	"candidate_site":{"kind":"S","coordinates":[0,0,0,10000]}}]
B=[{"face_index":1,"unknown_area_by_limiting_site":[
	{"site":{"kind":"P","coordinates":[0,0]},"area_m2":3},
	{"site":{"kind":"P","coordinates":[0,5000]},"area_m2":2},
	{"site":{"kind":"P","coordinates":[2000,5000]},"area_m2":1}]}]

class EndpointBlockerDominanceTests(unittest.TestCase):
	def test_endpoints_and_interior_are_non_strictly_dominated(self):
		r=audit_endpoint_blocker_dominance(C,B)[0]
		self.assertEqual(r["non_strict_related_area_m2"],5)
		self.assertEqual([x["non_strict_dominance_proven"] for x in r["blockers"]],
			[True,True,False])
		self.assertFalse(r["ownership_proven"])

	def test_extension_point_is_not_on_segment(self):
		b=[{"face_index":1,"unknown_area_by_limiting_site":[
			{"site":{"kind":"P","coordinates":[0,12000]},"area_m2":4}]}]
		self.assertFalse(audit_endpoint_blocker_dominance(C,b)[0]["blockers"][0]["point_on_candidate_segment"])

	def test_no_blockers_still_not_ownership(self):
		r=audit_endpoint_blocker_dominance(C,[{"face_index":1,"unknown_area_by_limiting_site":[]}])[0]
		self.assertFalse(r["ownership_proven"])

	def test_missing_candidate_rejected(self):
		with self.assertRaises(ValueError):
			audit_endpoint_blocker_dominance([] ,B)

	def test_zero_length_candidate_rejected(self):
		with self.assertRaises(ValueError):
			audit_endpoint_blocker_dominance(
				[{**C[0],"candidate_site":{"kind":"S","coordinates":[0,0,0,0]}}],B)

if __name__=="__main__":
	unittest.main()
