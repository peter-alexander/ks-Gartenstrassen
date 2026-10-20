import unittest
from shapely.geometry import LineString,box
from scripts.cgal_pair_constraints import audit_pair_constraints

A=("P",(0.,0.))
B=("P",(1000.,0.))
C=("P",(2000.,0.))

class PairConstraintTests(unittest.TestCase):
	def test_known_neighbor_fixes_unknown(self):
		faces=[box(0,0,1,1),box(1,0,2,1)]
		segments=[(LineString([(1,0),(1,1)]),(A,B))]
		result=audit_pair_constraints(faces,[None,B],segments)
		self.assertEqual(result[0]["solution_count_capped_at_2"],1)
		self.assertEqual(result[0]["unique_assignment"]["0"]["coordinates"],[0.,0.])

	def test_conflicting_same_boundary_is_not_guessed(self):
		faces=[box(0,0,1,1),box(1,0,2,1)]
		segments=[(LineString([(1,0),(1,1)]),(A,B)),
			(LineString([(1,0),(1,1)]),(A,C))]
		result=audit_pair_constraints(faces,[None,B],segments)
		self.assertEqual(result[0]["solution_count_capped_at_2"],0)
		self.assertIsNone(result[0]["unique_assignment"])

	def test_two_unknown_faces_are_ambiguous(self):
		faces=[box(0,0,1,1),box(1,0,2,1)]
		segments=[(LineString([(1,0),(1,1)]),(A,B))]
		result=audit_pair_constraints(faces,[None,None],segments)
		self.assertEqual(result[0]["solution_count_capped_at_2"],2)

if __name__=="__main__":
	unittest.main()
