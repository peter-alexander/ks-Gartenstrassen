import unittest
from scripts.cgal_endpoint_face_chain import audit_endpoint_face_chain

R={"edge_ids":[18,22],"third_edge_id":30,
	"status":"native_three_edge_adjacency_observed_only",
	"cyclic_order_proven":False,"ownership_proven":False,
	"pairwise_face_connections":[
		{"edge_ids":[18,22],"shared_face_ids":[]},
		{"edge_ids":[18,30],"shared_face_ids":[22]},
		{"edge_ids":[22,30],"shared_face_ids":[26]}]}


def check(pairs):
	return audit_endpoint_face_chain([{**R,"pairwise_face_connections":pairs}])[0]


class EndpointFaceChainTests(unittest.TestCase):
	def test_distinct_middle_face_links_are_diagnostic_only(self):
		result=audit_endpoint_face_chain([R])[0]
		self.assertEqual(result["status"],"native_face_chain_confirmed_not_ownership")
		self.assertEqual(result["shared_with_third"],[
			{"edge_id":18,"face_id":22},{"edge_id":22,"face_id":26}])
		self.assertFalse(result["cyclic_order_proven"])
		self.assertFalse(result["ownership_proven"])

	def test_direct_group_neighbor_blocks(self):
		pairs=[{**R["pairwise_face_connections"][0],"shared_face_ids":[12]},
			*R["pairwise_face_connections"][1:]]
		self.assertEqual(check(pairs)["status"],"blocked_non_chain_or_incomplete_face_topology")

	def test_reused_middle_face_blocks(self):
		pairs=[*R["pairwise_face_connections"][:2],
			{**R["pairwise_face_connections"][2],"shared_face_ids":[22]}]
		self.assertEqual(check(pairs)["status"],"blocked_non_chain_or_incomplete_face_topology")

	def test_missing_middle_link_blocks(self):
		self.assertEqual(check(R["pairwise_face_connections"][:2])["status"],
			"blocked_non_chain_or_incomplete_face_topology")

	def test_overlapping_groups_raise(self):
		with self.assertRaises(ValueError):
			audit_endpoint_face_chain([R,R])

if __name__=="__main__":
	unittest.main()
