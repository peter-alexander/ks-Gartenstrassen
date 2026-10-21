import unittest
from scripts.cgal_endpoint_dual_ray_direction import audit_endpoint_dual_ray_directions

GROUP={"status":"native_cw_ccw_cycle_alignment_only","edge_ids":[25,26],
	"voronoi_side_proven":False,"ownership_proven":False,
	"ordered_links":[{"edge_id":i,"cycle_forward_matches_export":i==26}
		for i in (25,26,28)]}
RAYS={25:[[0,0,1,0]],26:[[0,0,0,1]],28:[[2,3,3,4]]}


class EndpointDualRayDirectionTests(unittest.TestCase):
	def test_ray_inventory_preserves_unproven_sides(self):
		row=audit_endpoint_dual_ray_directions([GROUP],RAYS)[0]
		self.assertEqual(row["status"],"native_endpoint_ray_directions_recorded_only")
		self.assertEqual([r["edge_id"] for r in row["rays"]],[25,26,28])
		self.assertFalse(row["voronoi_side_proven"])
		self.assertFalse(row["ownership_proven"])

	def test_missing_ray_blocks_and_retains_other_evidence(self):
		row=audit_endpoint_dual_ray_directions([GROUP],
			{25:RAYS[25],26:RAYS[26]})[0]
		self.assertEqual(row["status"],"blocked_endpoint_ray_direction_evidence")
		self.assertEqual(row["missing_ray_edge_ids"],[28])
		self.assertEqual([item["edge_id"] for item in row["rays"]],[25,26])
		self.assertFalse(row["voronoi_side_proven"])

	def test_zero_direction_blocks(self):
		bad={**RAYS,28:[[2,3,2,3]]}
		self.assertEqual(audit_endpoint_dual_ray_directions([GROUP],bad)[0]["status"],
			"blocked_endpoint_ray_direction_evidence")

	def test_multiple_rays_blocks(self):
		bad={**RAYS,25:[RAYS[25][0],RAYS[25][0]]}
		self.assertEqual(audit_endpoint_dual_ray_directions([GROUP],bad)[0]["status"],
			"blocked_endpoint_ray_direction_evidence")

	def test_unexpected_side_proof_blocks(self):
		bad={**GROUP,"voronoi_side_proven":True}
		self.assertEqual(audit_endpoint_dual_ray_directions([bad],RAYS)[0]["status"],
			"blocked_endpoint_ray_direction_evidence")


if __name__=="__main__":
	unittest.main()
