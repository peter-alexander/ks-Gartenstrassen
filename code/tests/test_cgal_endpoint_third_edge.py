import unittest
from scripts.cgal_endpoint_third_edge import audit_endpoint_third_edges

G={"status":"grouped_diagnostic_only","ownership_proven":False,
	"edge_ids":[18,22],"point_site":{"kind":"P","coordinates":[0,10000]}}
E=[{"edge_id":18,"primary_finite":False,"neighbor_finite":True},
	{"edge_id":22,"primary_finite":False,"neighbor_finite":True},
	{"edge_id":30,"primary_finite":True,"neighbor_finite":True,
	"other_sites":[{"kind":"S","coordinates":[0,10000,10000,10000]}]}]
S={"status":"native_incident_star_unordered_only","ownership_proven":False,
	"cyclic_order_proven":False,"edge_ids":[18,22],"point_site":G["point_site"],
	"incident_edges":E}

class ThirdEdgeTests(unittest.TestCase):
	def test_third_edge_does_not_prove_rotation(self):
		result=audit_endpoint_third_edges([G],[S])[0]
		self.assertEqual(result["third_edge_id"],30)
		self.assertEqual(result["status"],"third_native_edge_observed_no_rotation_proof")
		self.assertFalse(result["cyclic_order_proven"])
		self.assertFalse(result["ownership_proven"])

	def test_missing_third_edge_blocks(self):
		result=audit_endpoint_third_edges([G],[{**S,"incident_edges":E[:2]}])[0]
		self.assertEqual(result["status"],"blocked_missing_or_unexpected_third_edge")

	def test_wrong_finiteness_blocks(self):
		edges=[*E[:2],{**E[2],"neighbor_finite":False}]
		result=audit_endpoint_third_edges([G],[{**S,"incident_edges":edges}])[0]
		self.assertEqual(result["status"],"blocked_missing_or_unexpected_third_edge")

	def test_unexpected_rotation_claim_blocks(self):
		result=audit_endpoint_third_edges([G],[{**S,"cyclic_order_proven":True}])[0]
		self.assertEqual(result["status"],"blocked_missing_or_unexpected_third_edge")

	def test_mismatched_group_star_counts_rejected(self):
		with self.assertRaises(ValueError):
			audit_endpoint_third_edges([G],[])

if __name__=="__main__":
	unittest.main()
