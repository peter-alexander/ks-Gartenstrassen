"""Diagnostic benchmark selection and bounded native-run tests."""
import unittest
from scripts.benchmark_segment_voronoi import _samples, _timed_construct


class BoostBenchmarkTests(unittest.TestCase):
	def test_spatial_and_spread_samples_have_exact_size(self):
		keys=[((i,0),(i+1,0)) for i in range(100)]
		for method in ("near","spread"):
			subset=_samples(keys,10,method)
			self.assertEqual(len(subset),10)
			self.assertEqual(len(set(subset)),10)
			self.assertEqual(subset,_samples(keys,10,method))

	def test_full_size_returns_unchanged_keys(self):
		keys=[((0,0),(1,0)),((0,2),(1,2))]
		self.assertEqual(_samples(keys,5,"spread"),keys)
		self.assertEqual(_samples(keys,5,"near"),keys)

	def test_invalid_timeout_is_rejected(self):
		from scripts.benchmark_segment_voronoi import benchmark
		with self.assertRaisesRegex(ValueError,"timeout"):
			benchmark("missing","missing","missing",timeout=0)


if __name__=="__main__":
	unittest.main()
