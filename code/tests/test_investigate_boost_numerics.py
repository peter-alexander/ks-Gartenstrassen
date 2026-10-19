"""Regression tests for Boost numeric and insertion-order diagnostics."""
import unittest

from scripts.investigate_boost_numerics import (
	_geometry_report, _order_cases, _transform)


class BoostNumericTests(unittest.TestCase):
	def setUp(self):
		self.a=((0,0),(1000,0))
		self.b=((0,1000),(1000,1000))
		self.site=((2000,0),(3000,0))

	def test_order_variants_keep_exact_same_segment_set(self):
		base=[self.a,self.b]
		cases=_order_cases(base,self.site)
		self.assertEqual(cases[0][1],base+[self.site])
		self.assertEqual(cases[1][1],list(reversed(base+[self.site])))
		for _,keys in cases:
			self.assertEqual(set(keys),set(base+[self.site]))
			self.assertEqual(len(keys),3)

	def test_integer_translation_preserves_distances(self):
		frame=[(0.,0.),(10.,0.)]
		keys,new_frame=_transform([self.a,self.b],frame,
			dx=1000000,dy=-2000000)
		self.assertEqual(keys[0],((1000000,-2000000),(1001000,-2000000)))
		self.assertEqual(new_frame,[(1000.,-2000.),(1010.,-2000.)])

	def test_integer_scaling_transforms_frame_too(self):
		keys,frame=_transform([self.a],[(1.,2.)],multiplier=4)
		self.assertEqual(keys[0],((0,0),(4000,0)))
		self.assertEqual(frame,[(4.,8.)])

	def test_geometry_diagnostic_excludes_shared_vertex_pairs(self):
		site=self.a
		adjoining=((1000,0),(2000,0))
		other=((0,3),(500,3))
		keys=[site,adjoining,other]
		report=_geometry_report(keys,{site:"site",adjoining:"join",
			other:"near"},(0,0),site,tolerance_m=0.005)
		self.assertEqual(report["segments"],3)
		self.assertEqual(report["close_nonvertex_pairs"],1)
		self.assertEqual(report["vertex_degree_counts"]["2"],1)


if __name__=="__main__":
	unittest.main()
