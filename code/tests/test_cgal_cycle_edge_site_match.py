import unittest
from scripts.cgal_cycle_edge_site_match import audit_cycle_edge_site_match

SITES=[["S",0,0,0,10],["S",0,0,10,0],["S",0,-10,0,0]]
STAR={"status":"native_incident_star_unordered_only","ownership_proven":False,
	"edge_ids":[1,2],"incident_edges":[
		{"edge_id":i,"other_sites":[{"kind":"S","coordinates":site[1:]}]}
		for i,site in enumerate(SITES,1)]}
CYCLE={"status":"native_cycle_shared_sites_verified_only",
	"ownership_proven":False,"cyclic_order_proven":True,"edge_ids":[1,2],
	"adjacent_face_sites":[{"shared_other_site":site} for site in
		[SITES[0],["INF"],SITES[1],SITES[2]]]}


class CycleEdgeSiteMatchTests(unittest.TestCase):
	def test_complete_original_sites_are_not_owners(self):
		result=audit_cycle_edge_site_match([STAR],[CYCLE])[0]
		self.assertEqual(result["status"],"native_cycle_edge_sites_identical_only")
		self.assertEqual(len(result["matched_edges"]),3)
		self.assertFalse(result["ownership_proven"])

	def test_different_generator_blocks(self):
		bad={**CYCLE,"adjacent_face_sites":[*CYCLE["adjacent_face_sites"][:3],
			{"shared_other_site":["S",99,0,99,10]}]}
		self.assertEqual(audit_cycle_edge_site_match([STAR],[bad])[0]["status"],
			"blocked_cycle_edge_site_disagreement")

	def test_missing_infinity_blocks(self):
		bad={**CYCLE,"adjacent_face_sites":[
			{"shared_other_site":site} for site in [*SITES,SITES[0]]]}
		self.assertEqual(audit_cycle_edge_site_match([STAR],[bad])[0]["status"],
			"blocked_cycle_edge_site_disagreement")

	def test_ownership_claim_blocks(self):
		self.assertEqual(audit_cycle_edge_site_match([STAR],[{**CYCLE,"ownership_proven":True}])[0]["status"],
			"blocked_cycle_edge_site_disagreement")

	def test_missing_group_blocks(self):
		with self.assertRaises(ValueError):
			audit_cycle_edge_site_match([STAR],[])

if __name__=="__main__":
	unittest.main()
