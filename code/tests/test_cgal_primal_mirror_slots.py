import unittest
from scripts.cgal_primal_mirror_slots import audit_primal_mirror_slots

F={0:{"face_id":1,"neighbor_face_id":2}}
I={0:{"local_index":1,"neighbor_index":2}}
N={"faces":{1:[3,2,4],2:[5,6,1]},"ownership_proven":False}


class NativeMirrorSlotTests(unittest.TestCase):
	def test_mirrored_primal_edge_is_not_generator_ownership(self):
		result=audit_primal_mirror_slots(F,I,N)
		self.assertEqual(result[0]["status"],"native_mirror_slot_consistent_only")
		self.assertFalse(result[0]["cyclic_order_proven"])
		self.assertFalse(result[0]["ownership_proven"])

	def test_wrong_local_slot_rejected(self):
		with self.assertRaises(ValueError):
			audit_primal_mirror_slots(F,{0:{"local_index":0,"neighbor_index":2}},N)

	def test_wrong_mirror_slot_rejected(self):
		with self.assertRaises(ValueError):
			audit_primal_mirror_slots(F,{0:{"local_index":1,"neighbor_index":0}},N)

	def test_missing_face_data_rejected(self):
		with self.assertRaises(ValueError):
			audit_primal_mirror_slots(F,I,{"faces":{1:[3,2,4]},"ownership_proven":False})

	def test_unexpected_proof_claim_rejected(self):
		with self.assertRaises(ValueError):
			audit_primal_mirror_slots(F,I,{**N,"ownership_proven":True})

if __name__=="__main__":
	unittest.main()
