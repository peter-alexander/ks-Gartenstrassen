import unittest
from scripts.cgal_endpoint_primal_star import audit_endpoint_primal_star

P=("P",(0,0))
A=("S",(0,0,0,10))
B=("S",(0,-10,0,0))
I={"local_index":2,"neighbor_index":1,"primary_finite":False,
	"neighbor_finite":True,"opposite_sites":"OPP INF | NEIGH P 1 1"}
G={"status":"grouped_diagnostic_only","ownership_proven":False,
	"point_site":{"kind":"P","coordinates":[0,0]},"edge_ids":[1,2]}
E=[(1,(P,A),[]),(2,(P,B),[]),(3,(P,("P",(5,0))),[])]


class EndpointPrimalStarTests(unittest.TestCase):
	def test_full_point_incidence_inventory_does_not_prove_rotation(self):
		result=audit_endpoint_primal_star([G],E,{1:I,2:I,3:I})[0]
		self.assertEqual(result["status"],"native_incident_star_unordered_only")
		self.assertEqual([r["edge_id"] for r in result["incident_edges"]],[1,2,3])
		self.assertFalse(result["cyclic_order_proven"])
		self.assertFalse(result["ownership_proven"])

	def test_missing_incidence_blocks_inventory(self):
		result=audit_endpoint_primal_star([G],E,{1:I,2:I})[0]
		self.assertEqual(result["status"],"blocked_missing_native_star_evidence")

	def test_missing_group_edge_blocks_inventory(self):
		result=audit_endpoint_primal_star([G],E[1:],{1:I,2:I,3:I})[0]
		self.assertEqual(result["status"],"blocked_missing_native_star_evidence")

	def test_ownership_claim_blocks_inventory(self):
		result=audit_endpoint_primal_star([{**G,"ownership_proven":True}],E,{1:I,2:I,3:I})[0]
		self.assertEqual(result["status"],"blocked_invalid_group")


if __name__=="__main__":
	unittest.main()
