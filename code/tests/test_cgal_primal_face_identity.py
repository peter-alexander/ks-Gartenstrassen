import unittest
from scripts.cgal_primal_face_identity import parse_primal_face_pairs,audit_group_primal_faces

GROUP={"edge_ids":[18,22],"status":"grouped_diagnostic_only","ownership_proven":False}


class PrimalFaceIdentityTests(unittest.TestCase):
	def test_native_face_ids_are_not_ownership(self):
		pairs=parse_primal_face_pairs(["H 0 0 1","H 1 0 2"],2)
		result=audit_group_primal_faces([{**GROUP,"edge_ids":[0,1]}],pairs)[0]
		self.assertEqual(result["shared_face_ids"],[0])
		self.assertFalse(result["cyclic_order_proven"])
		self.assertFalse(result["ownership_proven"])

	def test_no_shared_face_is_not_invented(self):
		pairs=parse_primal_face_pairs(["H 0 0 1","H 1 2 3"],2)
		result=audit_group_primal_faces([{**GROUP,"edge_ids":[0,1]}],pairs)[0]
		self.assertEqual(result["shared_face_ids"],[])

	def test_duplicate_handle_on_edge_rejected(self):
		with self.assertRaises(ValueError):
			parse_primal_face_pairs(["H 0 1 1"],1)

	def test_missing_or_reordered_edge_rejected(self):
		with self.assertRaises(ValueError):
			parse_primal_face_pairs(["H 1 0 2"],1)

	def test_missing_group_identity_blocked(self):
		result=audit_group_primal_faces([GROUP],{18:{"face_id":0,"neighbor_face_id":1}})[0]
		self.assertEqual(result["status"],"blocked_incomplete_face_identity")

if __name__=="__main__":
	unittest.main()
