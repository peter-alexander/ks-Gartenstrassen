import unittest

from shapely.geometry import LineString,box

from scripts.cgal_generator_mismatch_audit import incompatible_candidates


A=("P",(1000.,1000.))
B=("P",(8000.,8000.))
C=("P",(15000.,15000.))


class GeneratorMismatchAuditTests(unittest.TestCase):
	def test_incompatible_site_has_dual_provenance(self):
		face=box(0,0,5,5)
		duals=[(LineString([(0,2),(5,2)]),(A,B))]
		result=incompatible_candidates([(face,B)],duals)
		self.assertEqual(len(result),1)
		self.assertGreater(result[0]["site_distance_m"],0)
		self.assertEqual(result[0]["intersecting_dual_count"],1)
		self.assertEqual(result[0]["claimed_site_boundary_records"],1)

	def test_compatible_and_unknown_sites_are_not_mismatches(self):
		face=box(0,0,5,5)
		self.assertEqual(incompatible_candidates([(face,A),(face,None)],[]),[])

	def test_diagnostics_do_not_infer_nearest_generator(self):
		face=box(0,0,5,5)
		data=incompatible_candidates([(face,C)],[])
		self.assertEqual(data[0]["claimed_site"]["kind"],"P")
		self.assertEqual(data[0]["incident_duals"],[])


if __name__=="__main__":
	unittest.main()
