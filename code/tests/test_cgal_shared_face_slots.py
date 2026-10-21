import unittest
from scripts.cgal_shared_face_slots import audit_shared_face_slots

V={
	18:{"face_ids":[1,2],"raw_slots":["1 0:P 0 0 1:P 1 0 2:INF","2 0:P 0 0 1:P 2 0 2:INF"]},
	22:{"face_ids":[3,4],"raw_slots":["3 0:P 0 0 1:P 3 0 2:INF","4 0:P 0 0 1:P 4 0 2:INF"]},
	30:{"face_ids":[2,3],"raw_slots":["2 0:P 0 0 1:P 2 0 2:INF","3 0:P 0 0 1:P 3 0 2:INF"]}}
C={"edge_ids":[18,22],"third_edge_id":30,
	"status":"native_face_chain_confirmed_not_ownership",
	"ownership_proven":False,"cyclic_order_proven":False,
	"shared_with_third":[{"edge_id":18,"face_id":2},{"edge_id":22,"face_id":3}]}


class SharedFaceSlotTests(unittest.TestCase):
	def test_matching_shared_face_slots_are_not_ownership(self):
		r=audit_shared_face_slots(V,[C])[0]
		self.assertEqual(r["status"],"shared_native_triangle_slots_identical_only")
		self.assertEqual(r["shared_face_ids"],[2,3])
		self.assertFalse(r["cyclic_order_proven"])
		self.assertFalse(r["ownership_proven"])

	def test_same_face_with_different_slots_rejected(self):
		bad={**V,30:{**V[30],"raw_slots":["2 0:P 5 5 1:P 2 0 2:INF",V[30]["raw_slots"][1]]}}
		with self.assertRaises(ValueError):
			audit_shared_face_slots(bad,[C])

	def test_missing_third_edge_blocks(self):
		r=audit_shared_face_slots({18:V[18],22:V[22]},[C])[0]
		self.assertEqual(r["status"],"blocked_missing_shared_triangle_slots")

	def test_unexpected_ownership_claim_blocks(self):
		r=audit_shared_face_slots(V,[{**C,"ownership_proven":True}])[0]
		self.assertEqual(r["status"],"blocked_missing_shared_triangle_slots")

if __name__=="__main__":
	unittest.main()
