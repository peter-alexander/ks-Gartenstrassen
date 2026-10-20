import unittest

from shapely.geometry import LineString,box

from scripts.cgal_repair_test_cells import repair_test_cells


A=("P",(0.,0.))
B=("P",(1500.,0.))
C=("P",(3000.,0.))


class ExperimentalRepairTests(unittest.TestCase):
	def test_complete_labelled_partition_remains_unchanged(self):
		window=box(0,0,3,2)
		sources=[(LineString([(1,0),(1,2)]),(A,B)),
			(LineString([(2,0),(2,2)]),(B,C))]
		polygons,labels,stats=repair_test_cells(window,sources)
		self.assertEqual(len(polygons),3)
		self.assertEqual(stats["repaired_parent_faces"],0)
		self.assertEqual(stats["original_proven"],1)
		self.assertEqual(stats["output_proven"],1)
		self.assertEqual(stats["still_unresolved"],2)

	def test_ambiguous_partition_must_remain_unresolved(self):
		window=box(0,0,3,2)
		sources=[(LineString([(1,0),(1,2)]),(A,B)),
			(LineString([(2,0),(2,2)]),(A,C))]
		_,_,stats=repair_test_cells(window,sources)
		self.assertEqual(stats["repaired_parent_faces"],0)
		self.assertEqual(stats["gap_m2"],0)
		self.assertEqual(stats["overlap_m2"],0)


if __name__=="__main__":
	unittest.main()
