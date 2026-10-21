import unittest
from scripts.cgal_primal_side_hypothesis import audit_primal_side_hypothesis

class PrimalSideHypothesisTests(unittest.TestCase):
	def test_supported_and_counterexample(self):
		base={"locally_verified":True,"local_index":0,"neighbor_index":1}
		observations=[
			{**base,"edge_id":1,"primary_finite":True,"neighbor_finite":False,
				"left_site_is_first":True},
			{**base,"edge_id":2,"primary_finite":False,"neighbor_finite":True,
				"left_site_is_first":True}]
		result=audit_primal_side_hypothesis(observations)
		self.assertEqual([x["status"] for x in result],
			["supported","counterexample"])

	def test_both_finite_are_not_predicted(self):
		result=audit_primal_side_hypothesis([{"edge_id":0,
			"locally_verified":True,"local_index":0,"neighbor_index":1,
			"primary_finite":True,"neighbor_finite":True,
			"left_site_is_first":False}])
		self.assertEqual(result[0]["status"],"untested")

if __name__=="__main__":
	unittest.main()
