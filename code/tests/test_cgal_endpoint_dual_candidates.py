import unittest
from shapely.geometry import LineString,box
from scripts.cgal_endpoint_dual_candidates import (
	audit_endpoint_dual_candidates,is_endpoint_pair)

P=("P",(1000.,1000.))
S=("S",(1000.,1000.,1000.,2000.))
A=("S",(2000.,0.,2000.,1000.))
B=("S",(0.,0.,0.,1000.))

class EndpointDualCandidateTests(unittest.TestCase):
	def test_endpoint_recognition(self):
		self.assertTrue(is_endpoint_pair((P,S)))
		self.assertTrue(is_endpoint_pair((S,P)))
		self.assertFalse(is_endpoint_pair((P,A)))

	def test_candidate_only_does_not_replace_label(self):
		window=box(0,0,2,2)
		face=box(0,0,1,1)
		segments=[
			(LineString([(1,0),(1,1)]),(S,A)),
			(LineString([(0,1),(1,1)]),(S,B)),
			(LineString([(0,0),(1,0)]),(P,S))]
		labels=[None]
		report=audit_endpoint_dual_candidates([face],labels,segments,window)
		self.assertEqual(labels,[None])
		self.assertTrue(report[0]["unique_ordinary_candidate"])
		self.assertEqual(report[0]["status"],"candidate_only_not_proven")
		self.assertEqual(report[0]["endpoint_conflicting_pairs"],0)

	def test_invalid_lengths(self):
		with self.assertRaises(ValueError):
			audit_endpoint_dual_candidates([box(0,0,1,1)],[],[],box(0,0,2,2))

if __name__=="__main__":
	unittest.main()
