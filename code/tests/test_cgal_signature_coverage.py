import unittest
from scripts.cgal_signature_coverage import FIXTURES,audit_signature_coverage


def fixtures(rows=None):
	return [{"fixture":name,"experimental_carried":{"primal_side_comparison":
		rows if name=="grid" and rows is not None else []}} for name in FIXTURES]


R={"edge_id":1,"locally_verified":True,"left_site_is_first":True,
	"local_index":0,"neighbor_index":1,"primary_finite":True,"neighbor_finite":False}


class SignatureCoverageTests(unittest.TestCase):
	def test_observations_counted_without_promotion(self):
		result=audit_signature_coverage(fixtures([R])) 
		self.assertEqual(result["verified_regular_edges"],1)
		self.assertFalse(result["ownership_proven"])
		self.assertEqual(result["signatures"][0]["status"],"one_sided_observations_only")

	def test_conflicting_regular_observations_are_not_suppressed(self):
		result=audit_signature_coverage(fixtures([R,{**R,"edge_id":2,"left_site_is_first":False}]))
		self.assertEqual(result["signatures"][0]["status"],"contradictory_regular_observations")

	def test_unverified_samples_ignored(self):
		result=audit_signature_coverage(fixtures([{**R,"locally_verified":False}]))
		self.assertEqual(result["verified_regular_edges"],0)

	def test_missing_fixture_rejected(self):
		with self.assertRaises(ValueError):
			audit_signature_coverage(fixtures()[:-1])

	def test_missing_native_rows_rejected(self):
		data=fixtures()
		data[0]["experimental_carried"]={}
		with self.assertRaises(ValueError):
			audit_signature_coverage(data)


if __name__=="__main__":
	unittest.main()
