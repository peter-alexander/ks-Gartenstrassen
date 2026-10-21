import unittest
from scripts.cgal_primal_face_vertices import parse_primal_face_vertices

F={0:{"face_id":3,"neighbor_face_id":4}}
LINE="V 0 | FACE 3 0:P 0 0 1:S 0 0 1 0 2:INF | FACE 4 0:P 0 0 1:P 1 0 2:S 0 0 1 0"


class NativeTriangleSlotTests(unittest.TestCase):
	def test_original_face_slots_only_no_ownership(self):
		result=parse_primal_face_vertices([LINE],1,F)[0]
		self.assertEqual(result["face_ids"],[3,4])
		self.assertFalse(result["cyclic_order_proven"])
		self.assertFalse(result["ownership_proven"])

	def test_wrong_face_handle_rejected(self):
		with self.assertRaises(ValueError):
			parse_primal_face_vertices([LINE.replace("FACE 4","FACE 5")],1,F)

	def test_missing_triangle_slot_rejected(self):
		with self.assertRaises(ValueError):
			parse_primal_face_vertices([LINE.replace("2:INF","")],1,F)

	def test_missing_record_rejected(self):
		with self.assertRaises(ValueError):
			parse_primal_face_vertices([],1,F)

if __name__=="__main__":
	unittest.main()
