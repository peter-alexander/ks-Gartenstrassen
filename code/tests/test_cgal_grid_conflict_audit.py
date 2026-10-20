import unittest

from shapely.geometry import LineString,box

from scripts.cgal_grid_conflict_audit import audit_conflicting_faces


A=("P",(1000.,1000.))
B=("P",(5000.,5000.))
C=("P",(9000.,9000.))
S=("S",(0.,0.,10000.,10000.))


class GridConflictAuditTests(unittest.TestCase):
	def test_conflict_and_segment_endpoint_relation(self):
		face=box(0,0,10,10)
		segments=[
			(LineString([(0,0),(10,0)]),(A,B)),
			(LineString([(0,10),(10,10)]),(B,C)),
			(LineString([(0,0),(0,10)]),(A,S))]
		result=audit_conflicting_faces([face],[None],segments)
		self.assertEqual(len(result),1)
		self.assertEqual(result[0]["common_generator_count"],0)
		self.assertEqual(result[0]["boundary_pair_count"],3)
		self.assertEqual(result[0]["boundary_edge_roles"]["point_point"]["fragments"],2)
		self.assertEqual(result[0]["boundary_edge_roles"]["point_segment"]["fragments"],1)
		self.assertGreaterEqual(len(result[0]["point_segment_endpoint_relations"]),1)

	def test_resolved_face_is_skipped(self):
		self.assertEqual(audit_conflicting_faces([box(0,0,10,10)],
			[A],[]),[])

	def test_invalid_arguments(self):
		with self.assertRaises(ValueError):
			audit_conflicting_faces([box(0,0,10,10)],[],[])


if __name__=="__main__":
	unittest.main()
