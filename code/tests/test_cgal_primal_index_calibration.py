import unittest
from scripts.cgal_primal_index_calibration import audit_primal_index_calibration

N={"edge_ids":[18,22],"status":"native_incidence_recorded_not_ownership",
	"ownership_proven":False,"native_records":[
	{"edge_id":18,"local_index":0,"neighbor_index":2,"primary_finite":False,"neighbor_finite":True},
	{"edge_id":22,"local_index":1,"neighbor_index":0,"primary_finite":False,"neighbor_finite":True}]}
R={"edge_id":4,"local_index":0,"neighbor_index":2,"primary_finite":False,
	"neighbor_finite":True,"locally_verified":True,"left_site_is_first":False}


class PrimalIndexCalibrationTests(unittest.TestCase):
	def test_exact_matches_are_observations_only(self):
		result=audit_primal_index_calibration([N],[R])[0]
		self.assertEqual(result["native_edges"][0]["regular_matching_edge_ids"],[4])
		self.assertEqual(result["native_edges"][1]["evidence_status"],"no_regular_match")
		self.assertFalse(result["ownership_proven"])

	def test_conflicting_regular_observations_reported(self):
		result=audit_primal_index_calibration([N],[R,{**R,"edge_id":5,"left_site_is_first":True}])[0]
		self.assertEqual(result["native_edges"][0]["evidence_status"],"conflicting_regular_observations")

	def test_unverified_regular_sample_ignored(self):
		result=audit_primal_index_calibration([N],[{**R,"locally_verified":False}])[0]
		self.assertEqual(result["native_edges"][0]["evidence_status"],"no_regular_match")

	def test_unproven_group_blocked(self):
		result=audit_primal_index_calibration([{**N,"ownership_proven":True}],[R])[0]
		self.assertEqual(result["status"],"blocked_invalid_group_incidence")

	def test_invalid_index_blocked(self):
		rows=[{**N["native_records"][0],"local_index":5},N["native_records"][1]]
		result=audit_primal_index_calibration([{**N,"native_records":rows}],[R])[0]
		self.assertEqual(result["status"],"blocked_invalid_group_incidence")


if __name__=="__main__":
	unittest.main()
