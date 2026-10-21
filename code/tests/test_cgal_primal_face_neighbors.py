import unittest
from scripts.cgal_primal_face_neighbors import parse_primal_face_neighbors

PAIRS={0:{"face_id":1,"neighbor_face_id":2}}
ROWS=["N 0 | FACE 1 0:3 1:2 2:4 | FACE 2 0:5 1:6 2:1"]


class PrimalFaceNeighborTests(unittest.TestCase):
	def test_original_neighbor_slots_remain_diagnostic(self):
		r=parse_primal_face_neighbors(ROWS,1,PAIRS)
		self.assertEqual(r["faces"][1],[3,2,4])
		self.assertFalse(r["cyclic_order_proven"])
		self.assertFalse(r["ownership_proven"])

	def test_misordered_face_rejected(self):
		with self.assertRaises(ValueError):
			parse_primal_face_neighbors([ROWS[0].replace("FACE 1","FACE 8")],1,PAIRS)

	def test_self_neighbor_rejected(self):
		with self.assertRaises(ValueError):
			parse_primal_face_neighbors([ROWS[0].replace("0:3","0:1")],1,PAIRS)

	def test_nonreciprocal_neighbor_rejected(self):
		with self.assertRaises(ValueError):
			parse_primal_face_neighbors([ROWS[0].replace("2:1","2:7")],1,PAIRS)

	def test_missing_record_rejected(self):
		with self.assertRaises(ValueError):
			parse_primal_face_neighbors([],1,PAIRS)

if __name__=="__main__":
	unittest.main()
