import unittest
from scripts.cgal_endpoint_dual_side_guard import audit_endpoint_dual_side_evidence

GROUP={"status":"native_cycle_dual_incidence_only","ownership_proven":False,
	"voronoi_side_proven":False,"edge_ids":[25,26],"cycle_links":[
		{"edge_id":25,"dual_kind":"degenerate_endpoint"},
		{"edge_id":None,"dual_kind":"unexported_infinite_link"},
		{"edge_id":26,"dual_kind":"degenerate_endpoint"},
		{"edge_id":28,"dual_kind":"degenerate_endpoint"}]}

class EndpointDualSideGuardTests(unittest.TestCase):
	def test_all_three_endpoint_duals_remain_unproven(self):
		row=audit_endpoint_dual_side_evidence([GROUP],[{"edge_id":7,"locally_verified":True}])[0]
		self.assertEqual(row["status"],"degenerate_duals_require_independent_side_proof")
		self.assertEqual(row["degenerate_edge_ids"],[25,26,28])
		self.assertFalse(row["ownership_proven"])
		self.assertFalse(row["voronoi_side_proven"])

	def test_mislabeled_third_edge_blocks(self):
		bad={**GROUP,"cycle_links":[*GROUP["cycle_links"][:3],
			{"edge_id":28,"dual_kind":"non_endpoint"}]}
		self.assertEqual(audit_endpoint_dual_side_evidence([bad],[])[0]["status"],
			"blocked_mixed_or_missing_side_evidence")

	def test_regular_side_overlap_blocks(self):
		self.assertEqual(audit_endpoint_dual_side_evidence([GROUP],
			[{"edge_id":28,"locally_verified":True}])[0]["status"],
			"blocked_mixed_or_missing_side_evidence")

	def test_missing_infinite_link_blocks(self):
		bad={**GROUP,"cycle_links":[*GROUP["cycle_links"][:3],
			{"edge_id":None,"dual_kind":"unexported_infinite_link"}]}
		self.assertEqual(audit_endpoint_dual_side_evidence([bad],[])[0]["status"],
			"blocked_mixed_or_missing_side_evidence")

	def test_ownership_claim_blocks(self):
		self.assertEqual(audit_endpoint_dual_side_evidence([{**GROUP,"ownership_proven":True}],[])[0]["status"],
			"blocked_mixed_or_missing_side_evidence")

if __name__=="__main__":
	unittest.main()
