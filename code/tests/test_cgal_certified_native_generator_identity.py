import unittest
from scripts.cgal_certified_native_generator_identity import audit_certified_native_generator_identity

BOUNDS=[{"face_index":1,"status":"full_area_distance_bound_verified_only",
	"unknown_area_m2":0,"ownership_proven":False}]
CAND=[{"face_index":1,"status":"candidate_only_not_proven",
	"candidate_site":{"kind":"S","coordinates":[0,0,0,10000]}}]
VERTICES={3:("S",(0.,0.,0.,10000.)),4:("P",(0.,0.))}
EDGES={6:(3,4)}

class NativeCertifiedGeneratorIdentityTests(unittest.TestCase):
	def test_unique_native_vertex_not_ownership(self):
		r=audit_certified_native_generator_identity(BOUNDS,CAND,VERTICES,EDGES)[0]
		self.assertEqual(r["native_generator_vertex_id"],3)
		self.assertEqual(r["native_incident_edge_ids"],[6])
		self.assertFalse(r["ownership_proven"])
		self.assertFalse(r["voronoi_side_proven"])

	def test_duplicate_native_generator_fails(self):
		with self.assertRaises(ValueError):
			audit_certified_native_generator_identity(BOUNDS,CAND,
				{**VERTICES,8:VERTICES[3]},EDGES)

	def test_missing_incident_edge_fails(self):
		with self.assertRaises(ValueError):
			audit_certified_native_generator_identity(BOUNDS,CAND,VERTICES,{})

	def test_unproven_distance_excluded(self):
		self.assertEqual(audit_certified_native_generator_identity(
			[{**BOUNDS[0],"unknown_area_m2":1}],CAND,VERTICES,EDGES),[])

	def test_false_ownership_guard(self):
		with self.assertRaises(ValueError):
			audit_certified_native_generator_identity(
				[{**BOUNDS[0],"ownership_proven":True}],CAND,VERTICES,EDGES)

if __name__=="__main__":
	unittest.main()
