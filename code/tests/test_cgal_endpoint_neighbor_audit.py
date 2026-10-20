import unittest
from shapely.geometry import LineString,box
from scripts.cgal_endpoint_neighbor_audit import audit_endpoint_neighbor_constraints

P=("P",(1000.,1000.))
S=("S",(1000.,1000.,1000.,2000.))
A=("S",(2000.,0.,2000.,1000.))
B=("S",(0.,0.,0.,1000.))

class EndpointNeighborAuditTests(unittest.TestCase):
	def test_known_neighbors_do_not_promote_unproven_endpoint_candidate(self):
		window=box(0,0,3,3)
		faces=[box(0,0,1,1),box(1,0,2,1)]
		segments=[
			(LineString([(1,0),(1,1)]),(S,A)),
			(LineString([(0,1),(1,1)]),(S,B)),
			(LineString([(0,0),(1,0)]),(P,S))]
		report=audit_endpoint_neighbor_constraints(faces,[None,A],segments,window)
		self.assertEqual(len(report),1)
		self.assertEqual(report[0]["known_neighbor_constraints"],1)
		self.assertEqual(report[0]["known_neighbor_mismatches"],0)
		self.assertFalse(report[0]["eligible_for_proof"])
		self.assertEqual(report[0]["blocking_reason"],
			"endpoint_side_ownership_not_proven")

	def test_known_neighbor_conflict_is_reported(self):
		window=box(0,0,3,3)
		faces=[box(0,0,1,1),box(1,0,2,1)]
		segments=[
			(LineString([(1,0),(1,1)]),(S,A)),
			(LineString([(0,1),(1,1)]),(S,B)),
			(LineString([(0,0),(1,0)]),(P,S))]
		report=audit_endpoint_neighbor_constraints(faces,[None,B],segments,window)
		self.assertEqual(report[0]["known_neighbor_mismatches"],1)
		self.assertEqual(report[0]["blocking_reason"],"known_neighbor_conflict")

	def test_no_candidate(self):
		self.assertEqual(audit_endpoint_neighbor_constraints(
			[box(0,0,1,1)],[None],[],box(0,0,2,2)),[])

if __name__=="__main__":
	unittest.main()
