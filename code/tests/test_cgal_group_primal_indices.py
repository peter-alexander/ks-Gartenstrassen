import unittest
from scripts.cgal_group_primal_indices import audit_group_primal_indices

GROUP={"status":"grouped_diagnostic_only","edge_ids":[18,22],"ownership_proven":False}
ROW={"local_index":0,"neighbor_index":2,"primary_finite":False,
	"neighbor_finite":True,"opposite_sites":"OPP INF | NEIGH P 1 2"}


class GroupPrimalIndexTests(unittest.TestCase):
	def test_preserves_both_native_index_pairs_without_promotion(self):
		other={**ROW,"local_index":1,"neighbor_index":0}
		report=audit_group_primal_indices([GROUP],{18:ROW,22:other})[0]
		self.assertEqual(report["status"],"native_incidence_recorded_not_ownership")
		self.assertFalse(report["same_local_index"])
		self.assertFalse(report["same_neighbor_index"])
		self.assertEqual(len(report["native_records"]),2)
		self.assertFalse(report["ownership_proven"])

	def test_different_opposite_sites_blocked(self):
		report=audit_group_primal_indices([GROUP],{18:ROW,22:{**ROW,"opposite_sites":"different"}})[0]
		self.assertEqual(report["status"],"blocked_incomplete_or_inconsistent_incidence")

	def test_invalid_local_index_blocked(self):
		report=audit_group_primal_indices([GROUP],{18:ROW,22:{**ROW,"local_index":3}})[0]
		self.assertEqual(report["status"],"blocked_incomplete_or_inconsistent_incidence")

	def test_missing_incidence_blocked(self):
		report=audit_group_primal_indices([GROUP],{18:ROW})[0]
		self.assertEqual(report["status"],"blocked_incomplete_or_inconsistent_incidence")

	def test_unexpected_ownership_claim_blocked(self):
		report=audit_group_primal_indices([{**GROUP,"ownership_proven":True}],{18:ROW,22:ROW})[0]
		self.assertEqual(report["status"],"blocked_incomplete_or_inconsistent_incidence")

	def test_reused_native_edge_rejected(self):
		with self.assertRaises(ValueError):
			audit_group_primal_indices([GROUP,{**GROUP,"edge_ids":[22,25]}],{18:ROW,22:ROW,25:ROW})


if __name__=="__main__":
	unittest.main()
