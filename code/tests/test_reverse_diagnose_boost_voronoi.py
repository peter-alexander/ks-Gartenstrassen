"""Verify order-preserving reversed Boost baseline isolation."""
import unittest

from scripts.reverse_diagnose_boost_voronoi import _reproduce_order
from scripts.diagnose_boost_voronoi import minimize


class ReverseBoostTests(unittest.TestCase):
	def test_preserves_original_boost_input_order(self):
		base=[("b",1),("b",2),("b",3),("b",4)]
		site=("target",1)
		self.assertEqual(
			_reproduce_order(base,site,[base[3],base[1]]),
			[base[1],base[3],site])

	def test_rejects_missing_or_duplicate_base_sites(self):
		with self.assertRaises(ValueError):
			_reproduce_order([1,2,3],9,[4])
		with self.assertRaises(ValueError):
			_reproduce_order([1,2,3],9,[2,2])

	def test_reduces_required_baseline_interaction(self):
		base=list(range(32))
		site=("target",)
		def wrapped(candidate,_frame):
			self.assertEqual(candidate[0],site)
			ordered=_reproduce_order(base,site,candidate[1:])
			self.assertEqual(ordered[-1],site)
			return {"status":"timeout" if 8 in ordered and 27 in ordered
				else "ok","wall_s":0.01}
		remaining,_,_=minimize([site],base,None,wrapped,max_tests=150)
		self.assertEqual(set(remaining),{8,27})


if __name__=="__main__":
	unittest.main()
