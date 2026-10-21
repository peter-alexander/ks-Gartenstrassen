import unittest
from scripts.cgal_endpoint_dual_primitives import audit_endpoint_dual_primitives

S={"status":"native_incident_star_unordered_only","ownership_proven":False,
	"edge_ids":[25,26],"incident_edges":[{"edge_id":i} for i in (25,26,28)]}
R={"status":"blocked_endpoint_ray_direction_evidence",
	"ownership_proven":False,"voronoi_side_proven":False,
	"missing_ray_edge_ids":[28]}
E=[(25,(),[("R",[0,0,1,0])]),(26,(),[("R",[0,0,1,0])]),
	(28,(),[("S",[0,0,2,0])])]


class EndpointPrimitiveTests(unittest.TestCase):
	def test_records_rays_and_nonray_without_side_proof(self):
		row=audit_endpoint_dual_primitives([S],[R],E)[0]
		self.assertEqual(row["status"],"native_endpoint_dual_primitives_recorded_only")
		self.assertEqual([x["primitives"][0]["kind"] for x in row["edge_primitives"]],
			["R","R","S"])
		self.assertFalse(row["voronoi_side_proven"])
		self.assertFalse(row["ownership_proven"])

	def test_missing_primitive_blocks(self):
		row=audit_endpoint_dual_primitives([S],[R],E[:2])[0]
		self.assertEqual(row["status"],"blocked_endpoint_dual_primitive_evidence")

	def test_invalid_coordinates_block(self):
		bad=[*E[:2],(28,(),[("S",[0,0,float("nan"),0])])]
		row=audit_endpoint_dual_primitives([S],[R],bad)[0]
		self.assertEqual(row["status"],"blocked_endpoint_dual_primitive_evidence")

	def test_invalid_kind_blocks(self):
		bad=[*E[:2],(28,(),[("Q",[0,0,1,0])])]
		row=audit_endpoint_dual_primitives([S],[R],bad)[0]
		self.assertEqual(row["status"],"blocked_endpoint_dual_primitive_evidence")

	def test_ownership_claim_blocks(self):
		row=audit_endpoint_dual_primitives([S],[{**R,"ownership_proven":True}],E)[0]
		self.assertEqual(row["status"],"blocked_endpoint_dual_primitive_evidence")

if __name__=="__main__":
	unittest.main()
