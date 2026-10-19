"""Coordinate shift and finite Voronoi comparison diagnostics."""
import unittest
from types import SimpleNamespace

from scripts.investigate_boost_translation import _case, _comparison, _digest, _signature


class TranslationDiagnosticTests(unittest.TestCase):
	def setUp(self):
		self.sites=[((0,100),(1000,100))]
		self.frame=[(-10.,-10.),(10.,-10.)]

	def test_pure_translation_moves_frame_and_sites(self):
		case=_case(self.sites,self.frame,"test",1000,-2000)
		self.assertEqual(case["sites"],[((1000,-1900),(2000,-1900))])
		self.assertEqual(case["frame"],[(-9.,-12.),(11.,-12.)])
		self.assertEqual(case["undo"],(1.,-2.))

	def test_frame_only_does_not_shift_sites(self):
		case=_case(self.sites,self.frame,"frame_only",1000,0,
			move_sites=False)
		self.assertEqual(case["sites"],self.sites)
		self.assertEqual(case["frame"],[(-9.,-10.),(11.,-10.)])
		self.assertEqual(case["undo"],(0.,0.))

	def test_comparison_tracks_missing_finite_edges(self):
		control={"status":"ok","vertices":{(1,2),(3,4)},
			"finite_linear":{((1,2),(3,4))}}
		variant={"status":"ok","vertices":{(1,2)},
			"finite_linear":set()}
		result=_comparison(variant,control)
		self.assertEqual(result["metrics"]["finite_linear"]["only_reference"],1)
		self.assertEqual(result["metrics"]["vertices"]["only_reference"],1)
		self.assertEqual(result["status"],"compared")

	def test_hash_is_order_independent(self):
		self.assertEqual(_digest({(1,2),(3,4)}),
			_digest({(3,4),(1,2)}))

	def test_rejects_noninteger_shift(self):
		with self.assertRaises(ValueError):
			_case(self.sites,self.frame,"invalid",0.5,0)

	def test_nonfinite_vertices_are_reported_and_excluded(self):
		class Diagram:
			def EnumerateVertices(self):
				return list(enumerate([
					SimpleNamespace(X=0.0,Y=0.0),
					SimpleNamespace(X=float("nan"),Y=2.0),
					SimpleNamespace(X=3.0,Y=4.0)]))
			def EnumerateEdges(self):
				return list(enumerate([
					SimpleNamespace(start=0,end=1,is_primary=True,is_linear=True),
					SimpleNamespace(start=0,end=2,is_primary=True,is_linear=True),
					SimpleNamespace(start=-1,end=2,is_primary=False,is_linear=False)]))
			def CountEdges(self):
				return 3
			def CountCells(self):
				return 2
		data=_signature(Diagram(),(0.,0.),0.01)
		self.assertEqual(data["nonfinite_vertices"],1)
		self.assertEqual(data["directed_edges_with_nonfinite_vertices"],1)
		self.assertEqual(data["directed_infinite"],1)
		self.assertEqual(len(data["finite_linear"]),1)
		self.assertEqual(data["raw_edges"],3)


if __name__=="__main__":
	unittest.main()
