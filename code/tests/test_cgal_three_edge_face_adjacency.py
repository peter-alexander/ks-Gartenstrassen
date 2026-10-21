import unittest
from scripts.cgal_three_edge_face_adjacency import audit_three_edge_face_adjacency

T={"edge_ids":[18,22],"third_edge_id":30,
	"status":"third_native_edge_observed_no_rotation_proof",
	"cyclic_order_proven":False,"ownership_proven":False}
F={18:{"face_id":1,"neighbor_face_id":2},
	22:{"face_id":3,"neighbor_face_id":4},
	30:{"face_id":2,"neighbor_face_id":3}}


class ThreeEdgeFaceAdjacencyTests(unittest.TestCase):
	def test_third_edge_bridges_two_distinct_faces_without_ownership(self):
		result=audit_three_edge_face_adjacency([T],F)[0]
		self.assertEqual([r["shared_face_ids"] for r in result["pairwise_face_connections"]],
			[[],[2],[3]])
		self.assertFalse(result["cyclic_order_proven"])
		self.assertFalse(result["ownership_proven"])

	def test_all_disjoint_is_reported_not_invented(self):
		result=audit_three_edge_face_adjacency([T],{**F,30:{"face_id":5,"neighbor_face_id":6}})[0]
		self.assertTrue(all(not r["shared_face_ids"] for r in result["pairwise_face_connections"]))

	def test_missing_third_edge_blocks(self):
		result=audit_three_edge_face_adjacency([T],{18:F[18],22:F[22]})[0]
		self.assertEqual(result["status"],"blocked_incomplete_three_edge_face_evidence")

	def test_ownership_claim_blocks(self):
		result=audit_three_edge_face_adjacency([{**T,"ownership_proven":True}],F)[0]
		self.assertEqual(result["status"],"blocked_incomplete_three_edge_face_evidence")

if __name__=="__main__":
	unittest.main()
