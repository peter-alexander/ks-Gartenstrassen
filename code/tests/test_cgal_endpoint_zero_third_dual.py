import unittest
from scripts.cgal_endpoint_zero_third_dual import audit_endpoint_zero_length_third_dual

STAR={"status":"native_incident_star_unordered_only","ownership_proven":False,
	"edge_ids":[25,26]}
GROUP={"status":"native_endpoint_dual_primitives_recorded_only",
	"ownership_proven":False,"voronoi_side_proven":False,
	"edge_primitives":[
		{"edge_id":25,"primitives":[{"kind":"R","coordinates":[20,10,21,10]}]},
		{"edge_id":26,"primitives":[{"kind":"R","coordinates":[20,10,21,10]}]},
		{"edge_id":28,"primitives":[{"kind":"S","coordinates":[20,10,20,10]}]}]}

class ZeroThirdDualTests(unittest.TestCase):
	def test_coincident_rays_and_zero_third_without_owner(self):
		row=audit_endpoint_zero_length_third_dual([STAR],[GROUP])[0]
		self.assertEqual(row["status"],"native_coincident_rays_zero_third_dual_only")
		self.assertEqual(row["third_edge_id"],28)
		self.assertFalse(row["voronoi_side_proven"])
		self.assertFalse(row["ownership_proven"])

	def test_nonzero_third_blocks(self):
		bad={**GROUP,"edge_primitives":[*GROUP["edge_primitives"][:2],
			{"edge_id":28,"primitives":[{"kind":"S","coordinates":[20,10,21,10]}]}]}
		self.assertEqual(audit_endpoint_zero_length_third_dual([STAR],[bad])[0]["status"],
			"blocked_endpoint_dual_geometry_pattern")

	def test_opposing_rays_block(self):
		bad={**GROUP,"edge_primitives":[GROUP["edge_primitives"][0],
			{"edge_id":26,"primitives":[{"kind":"R","coordinates":[20,10,19,10]}]},
			GROUP["edge_primitives"][2]]}
		self.assertEqual(audit_endpoint_zero_length_third_dual([STAR],[bad])[0]["status"],
			"blocked_endpoint_dual_geometry_pattern")

	def test_missing_third_blocks(self):
		bad={**GROUP,"edge_primitives":GROUP["edge_primitives"][:2]}
		self.assertEqual(audit_endpoint_zero_length_third_dual([STAR],[bad])[0]["status"],
			"blocked_endpoint_dual_geometry_pattern")

	def test_ownership_claim_blocks(self):
		self.assertEqual(audit_endpoint_zero_length_third_dual([STAR],
			[{**GROUP,"ownership_proven":True}])[0]["status"],
			"blocked_endpoint_dual_geometry_pattern")

if __name__=="__main__":
	unittest.main()
