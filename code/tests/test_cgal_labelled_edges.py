import unittest

from scripts.cgal_labelled_edges import labelled_edges


class LabelledEdgesTests(unittest.TestCase):
	def test_two_generators_and_parabola_fragments(self):
		stream=[
			"E 0 P 0 0 | S 0 10 20 10",
			"S 1 2 3 4",
			"S 3 4 5 6",
			"E 1 S 0 0 10 0 | P 10 10",
			"R 1 2 3 4"
		]
		edges=list(labelled_edges(stream))
		self.assertEqual(len(edges),2)
		self.assertEqual(edges[0][0],0)
		self.assertEqual(edges[0][1][0],("P",(0.,0.)))
		self.assertEqual(edges[0][1][1],("S",(0.,10.,20.,10.)))
		self.assertEqual(len(edges[0][2]),2)
		self.assertEqual(edges[1][2][0][0],"R")

	def test_empty_edge_can_precede_next(self):
		edges=list(labelled_edges([
			"E 0 P 0 0 | P 1 0",
			"E 1 P 1 0 | P 2 0",
			"S 0 0 1 1"]))
		self.assertEqual(len(edges[0][2]),0)
		self.assertEqual(len(edges[1][2]),1)

	def test_invalid_order_rejected(self):
		with self.assertRaises(ValueError):
			list(labelled_edges(["S 0 0 1 1"]))
		with self.assertRaises(ValueError):
			list(labelled_edges(["E 2 P 0 0 | P 1 1"]))


if __name__=="__main__":
	unittest.main()
