import unittest
from shapely.geometry import LineString,box
from scripts.cgal_shared_boundary_audit import audit_shared_boundaries

A=("P",(0.,0.))
B=("P",(1000.,0.))
C=("P",(2000.,0.))

class SharedBoundaryAuditTests(unittest.TestCase):
	def test_matching_fragment(self):
		faces=[box(0,0,1,1),box(1,0,2,1)]
		data=audit_shared_boundaries(faces,[None,B],
			[(LineString([(1,0),(1,1)]),(A,B))])
		self.assertEqual(len(data),1)
		self.assertEqual(data[0]["missing_length_m"],0)
		self.assertEqual(data[0]["multiply_labelled_spans"],0)

	def test_conflicting_overlapping_pairs(self):
		faces=[box(0,0,1,1),box(1,0,2,1)]
		data=audit_shared_boundaries(faces,[None,B],
			[(LineString([(1,0),(1,1)]),(A,B)),
				(LineString([(1,0),(1,1)]),(A,C))])
		self.assertGreater(data[0]["multiply_labelled_spans"],0)
		self.assertEqual(data[0]["distinct_source_pairs"],2)

	def test_point_contact_does_not_cover_edge(self):
		faces=[box(0,0,1,1),box(1,0,2,1)]
		data=audit_shared_boundaries(faces,[None,B],
			[(LineString([(0,0),(1,0)]),(A,B))])
		self.assertEqual(data[0]["source_fragment_count"],0)
		self.assertEqual(data[0]["missing_length_m"],1)

if __name__=="__main__":
	unittest.main()
