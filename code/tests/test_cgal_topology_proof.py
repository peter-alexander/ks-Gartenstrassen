import unittest

from shapely.geometry import LineString,box

from scripts.cgal_topology_proof import reconstruct_test_cells


A=("P",(0.,0.))
B=("P",(1.5,0.))
C=("P",(3.,0.))
D=("P",(4.,0.))


class CgalTopologyProofTests(unittest.TestCase):
	def test_middle_cell_has_unique_generator_from_two_bisectors(self):
		window=box(0,0,3,2)
		edges=[
			(LineString([(1,0),(1,2)]),(A,B)),
			(LineString([(2,0),(2,2)]),(B,C))]
		polygons,labels,stats=reconstruct_test_cells(window,edges)
		self.assertEqual(len(polygons),3)
		middle=[i for i,p in enumerate(polygons)
			if p.contains(box(1.2,.4,1.8,1.6))]
		self.assertEqual(len(middle),1)
		self.assertEqual(labels[middle[0]],B)
		self.assertEqual(stats["proven"],1)
		self.assertEqual(stats["insufficient_incidence"],2)

	def test_conflicting_generator_pairs_must_not_assign(self):
		window=box(0,0,3,2)
		edges=[
			(LineString([(1,0),(1,2)]),(A,B)),
			(LineString([(2,0),(2,2)]),(C,D))]
		polygons,labels,stats=reconstruct_test_cells(window,edges)
		middle=[i for i,p in enumerate(polygons)
			if p.contains(box(1.2,.4,1.8,1.6))]
		self.assertIsNone(labels[middle[0]])
		self.assertEqual(stats["conflicting_labels"],1)

	def test_incomplete_incidence_is_not_accepted(self):
		window=box(0,0,3,2)
		edges=[(LineString([(1,0),(1,2)]),(A,B))]
		polygons,labels,stats=reconstruct_test_cells(window,edges)
		self.assertEqual(stats["proven"],0)
		self.assertEqual(labels,[None,None])

	def test_diagnostic_reports_exact_missing_boundary_section(self):
		window=box(0,0,3,2)
		# This extra terminating line creates a fragment the labelled
		# segments cannot explain only if the reference is incomplete.
		edges=[
			(LineString([(1,0),(1,2)]),(A,B)),
			(LineString([(2,0),(2,2)]),(B,C))]
		polygons,labels,stats=reconstruct_test_cells(window,edges,
			diagnose=True)
		self.assertEqual(stats["proven"],1)
		self.assertEqual(stats["diagnostic_examples"],[])

	def test_conflict_examples_are_explicit(self):
		edges=[(LineString([(1,0),(1,2)]),(A,B)),
			(LineString([(2,0),(2,2)]),(C,D))]
		_,_,stats=reconstruct_test_cells(box(0,0,3,2),edges,
			diagnose=True)
		self.assertTrue(any(e["reason"]=="conflicting_labels"
			for e in stats["diagnostic_examples"]))

	def test_invalid_edge_is_rejected(self):
		with self.assertRaises(ValueError):
			reconstruct_test_cells(box(0,0,2,2),[
				(LineString([(1,0),(1,2)]),(A,A))])


if __name__=="__main__":
	unittest.main()
