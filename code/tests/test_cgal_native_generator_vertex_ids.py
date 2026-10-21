import unittest
from scripts.cgal_native_generator_vertex_ids import (
	parse_native_generator_ids,audit_native_generator_id_pairs,
)


class NativeGeneratorVertexIdsTests(unittest.TestCase):
	def test_original_generator_identity_crosschecks_dual_site_pair(self):
		vertices,ids=parse_native_generator_ids(
			"V 0 P 0 0\nV 1 S 0 0 10000 0\nG 0 0 1\n")
		report=audit_native_generator_id_pairs(vertices,ids,
			[(0,(("P",(0.,0.)),("S",(0.,0.,10000.,0.))),[])])
		self.assertEqual(report[0]["native_vertex_ids"],[0,1])
		self.assertFalse(report[0]["ownership_proven"])

	def test_swapped_generator_pair_is_identical_edge(self):
		vertices,ids=parse_native_generator_ids(
			"V 0 P 0 0\nV 1 S 0 0 10000 0\nG 0 1 0\n")
		audit_native_generator_id_pairs(vertices,ids,
			[(0,(("P",(0.,0.)),("S",(0.,0.,10000.,0.))),[])])

	def test_missing_generator_id_rejected(self):
		with self.assertRaises(ValueError):
			parse_native_generator_ids("V 0 P 0 0\nG 0 0 1\n")

	def test_duplicate_edge_id_rejected(self):
		with self.assertRaises(ValueError):
			parse_native_generator_ids("V 0 P 0 0\nV 1 P 1 0\nG 0 0 1\nG 0 0 1\n")

	def test_mismatched_generator_site_rejected(self):
		vertices,ids=parse_native_generator_ids(
			"V 0 P 0 0\nV 1 S 0 0 10000 0\nG 0 0 1\n")
		with self.assertRaises(ValueError):
			audit_native_generator_id_pairs(vertices,ids,
				[(0,(("P",(7.,0.)),("S",(0.,0.,10000.,0.))),[])])

if __name__=="__main__":
	unittest.main()
