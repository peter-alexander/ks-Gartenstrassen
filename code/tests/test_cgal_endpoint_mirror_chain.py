import unittest
from scripts.cgal_endpoint_mirror_chain import audit_endpoint_mirror_chain

C={"edge_ids":[18,22],"third_edge_id":30,
	"status":"native_face_chain_confirmed_not_ownership",
	"cyclic_order_proven":False,"ownership_proven":False,
	"shared_with_third":[{"edge_id":18,"face_id":2},
		{"edge_id":22,"face_id":3}]}
F={18:{"face_id":1,"neighbor_face_id":2},
	22:{"face_id":3,"neighbor_face_id":4},
	30:{"face_id":2,"neighbor_face_id":3}}
I={18:{"local_index":0,"neighbor_index":0},
	22:{"local_index":0,"neighbor_index":0},
	30:{"local_index":1,"neighbor_index":1}}
N={"faces":{1:[2,5,6],2:[1,3,7],3:[4,2,8],4:[3,9,10]},
	"ownership_proven":False}


class EndpointMirrorChainTests(unittest.TestCase):
	def test_verified_chain_is_not_cyclic_proof(self):
		row=audit_endpoint_mirror_chain([C],F,I,N)[0]
		self.assertEqual(row["status"],"mirror_chain_consistent_no_rotation_proof")
		self.assertFalse(row["cyclic_order_proven"])
		self.assertFalse(row["ownership_proven"])

	def test_wrong_bridge_mirror_blocks(self):
		bad={**N,"faces":{**N["faces"],2:[1,9,7]}}
		self.assertEqual(audit_endpoint_mirror_chain([C],F,I,bad)[0]["status"],
			"blocked_mirror_chain_evidence")

	def test_missing_edge_blocks(self):
		self.assertEqual(audit_endpoint_mirror_chain([C],F,{18:I[18],22:I[22]},N)[0]["status"],
			"blocked_mirror_chain_evidence")

	def test_ownership_claim_blocks(self):
		self.assertEqual(audit_endpoint_mirror_chain([{**C,"ownership_proven":True}],F,I,N)[0]["status"],
			"blocked_mirror_chain_evidence")


if __name__=="__main__":
	unittest.main()
