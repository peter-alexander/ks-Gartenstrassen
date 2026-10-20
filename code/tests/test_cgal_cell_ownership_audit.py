"""Synthetic regression cases for the independent CGAL/SIS owner audit."""
import unittest

from pyproj import Transformer
from shapely.geometry import box, LineString, mapping
from shapely.ops import transform

from scripts.audit_cgal_cell_ownership import audit


TO_WGS=Transformer.from_crs(31256,4326,always_xy=True).transform


def feature(edge,geometry):
	return {"type":"Feature","properties":{"edge_id":edge},
		"geometry":mapping(transform(TO_WGS,geometry))}


class OwnerAuditTests(unittest.TestCase):
	def setUp(self):
		self.axes={
			"a":LineString([(0,0),(0,10)]),
			"b":LineString([(10,0),(10,10)])}

	def test_correct_halves(self):
		features=[feature("a",box(-1,1,4,9)),
			feature("b",box(6,1,11,9))]
		result=audit(features,self.axes)
		self.assertEqual(result["failures"],0)
		self.assertGreaterEqual(result["sample_points"],2)

	def test_swapped_owner_is_reported(self):
		result=audit([feature("b",box(-1,1,3,9))],self.axes)
		self.assertGreater(result["failures"],0)
		self.assertEqual(result["details"][0]["nearest_edge_id"],"a")

	def test_missing_owner_rejected(self):
		with self.assertRaises(ValueError):
			audit([feature("missing",box(1,1,2,2))],self.axes)

	def test_tolerance_rejected(self):
		with self.assertRaises(ValueError):
			audit([],self.axes,tolerance_m=float("nan"))


if __name__=="__main__":
	unittest.main()
