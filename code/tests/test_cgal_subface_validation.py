import unittest

from shapely.geometry import LineString,box

from scripts.cgal_subface_validation import inspect_subfaces


A=("P",(0.,0.))
B=("P",(1000.,0.))
C=("P",(2000.,0.))


class SubfaceValidationTests(unittest.TestCase):
	def test_two_divided_faces_cover_parent_without_overlaps(self):
		parent=box(0,0,10,10)
		segments=[(LineString([(5,0),(5,10)]),(A,B))]
		data=inspect_subfaces(parent,segments)
		self.assertEqual(data["subfaces"],2)
		self.assertTrue(data["geometry_valid"])
		self.assertAlmostEqual(data["gap_m2"],0)
		self.assertAlmostEqual(data["overlap_m2"],0)
		self.assertEqual(data["proven_subfaces"],0)
		self.assertIn("independent_comparison",data)
		self.assertEqual(len(data["excluded_ring_details"]),data["filtered_out_rings"])

	def test_open_internal_cut_does_not_create_spurious_subfaces(self):
		data=inspect_subfaces(box(0,0,10,10),[
			(LineString([(5,5),(5,10)]),(A,B))])
		self.assertEqual(data["subfaces"],1)
		self.assertEqual(data["cuts"],1)
		self.assertEqual(data["proven_subfaces"],0)

	def test_reject_invalid_parent(self):
		with self.assertRaises(ValueError):
			inspect_subfaces(box(0,0,0,0),[])


if __name__=="__main__":
	unittest.main()
