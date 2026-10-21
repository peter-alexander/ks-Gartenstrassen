import unittest
from scripts.cgal_targeted_signature_probes import parse_signature_records,PROBES

T=["T 0 0 CW P 0 0 | CCW P 1 0","T 1 1 CW P 0 0 | CCW S 0 0 0 1"]
F=["F 0 2 2 0 1 OPP INF | NEIGH P 1 1",
	"F 1 1 2 0 1 OPP INF | NEIGH S 0 0 0 1"]


class TargetedSignatureProbeTests(unittest.TestCase):
	def test_regular_and_endpoint_targets_stay_distinct(self):
		rows=parse_signature_records(T,F)
		self.assertTrue(all(r["target_signature"] for r in rows))
		self.assertFalse(rows[0]["endpoint_dual"])
		self.assertTrue(rows[1]["endpoint_dual"])
		self.assertTrue(all(not r["ownership_proven"] for r in rows))

	def test_mismatched_counts_rejected(self):
		with self.assertRaises(ValueError):
			parse_signature_records(T,F[:1])

	def test_unexpected_record_index_rejected(self):
		with self.assertRaises(ValueError):
			parse_signature_records(T,[F[1],F[0]])

	def test_invalid_index_rejected(self):
		with self.assertRaises(ValueError):
			parse_signature_records(T,[F[0].replace(" 2 2 "," 4 2 "),F[1]])

	def test_distinct_synthetic_inputs(self):
		self.assertEqual(len(PROBES),len(set(PROBES.values())))


if __name__=="__main__":
	unittest.main()
