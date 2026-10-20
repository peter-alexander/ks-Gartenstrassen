import unittest

from shapely.geometry import LineString,box

from scripts.cgal_internal_dual_audit import audit_internal_duals


A=("P",(0.,0.))
B=("P",(1000.,0.))


class InternalDualAuditTests(unittest.TestCase):
	def test_open_internal_dual_does_not_split_cell(self):
		face=box(0,0,10,10)
		edge=LineString([(5,5),(5,10)])
		data=audit_internal_duals([face],[None],[(edge,(A,B))])[0]
		self.assertEqual(data["polygonized_subfaces"],1)
		self.assertGreater(data["cuts"]+data["dangles"],0)
		self.assertEqual(data["generator_pairs"],1)

	def test_full_divider_splits_cell(self):
		face=box(0,0,10,10)
		edge=LineString([(5,0),(5,10)])
		data=audit_internal_duals([face],[None],[(edge,(A,B))])[0]
		self.assertEqual(data["polygonized_subfaces"],2)
		self.assertEqual(data["cuts"],0)
		self.assertEqual(data["dangles"],0)

	def test_only_unresolved_faces_are_inspected(self):
		face=box(0,0,10,10)
		self.assertEqual(audit_internal_duals([face],[A],[]),[])


if __name__=="__main__":
	unittest.main()
