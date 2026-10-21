import unittest
from scripts.cgal_vertex_star_face_cycle_join import audit_vertex_star_face_cycles

STAR=[{"point_vertex_id":10,"status":"native_vertex_star_unordered_no_owner",
	"ownership_proven":False,"unresolved_ray_edge_ids":[18,22],
	"incident_native_edges":[{"edge_id":18},{"edge_id":22},{"edge_id":30}]}]
CYCLE=[{"edge_ids":[18,22],"status":"complete_native_face_cycle_only",
	"cyclic_order_proven":True,"ownership_proven":False,
	"face_cycle":[2,15,30,25]}]
PAIRS={18:{"face_id":2,"neighbor_face_id":15},
	22:{"face_id":30,"neighbor_face_id":25},
	30:{"face_id":15,"neighbor_face_id":30}}

class VertexStarFaceCycleTests(unittest.TestCase):
	def test_three_incident_edges_crosscheck_four_native_faces(self):
		row=audit_vertex_star_face_cycles(STAR,CYCLE,PAIRS)[0]
		self.assertEqual(row["status"],"complete_native_vertex_star_face_cycle_only")
		self.assertEqual(len(row["incident_edge_face_pairs"]),3)
		self.assertTrue(row["cyclic_order_proven"])
		self.assertFalse(row["ownership_proven"])

	def test_missing_collapsed_third_edge_blocks(self):
		row=audit_vertex_star_face_cycles(STAR,CYCLE,{18:PAIRS[18],22:PAIRS[22]})[0]
		self.assertEqual(row["status"],"blocked_vertex_star_face_cycle_mismatch")

	def test_third_edge_outside_cycle_blocks(self):
		row=audit_vertex_star_face_cycles(STAR,CYCLE,
			{**PAIRS,30:{"face_id":15,"neighbor_face_id":99}})[0]
		self.assertEqual(row["status"],"blocked_vertex_star_face_cycle_mismatch")

	def test_incomplete_cycle_blocks(self):
		row=audit_vertex_star_face_cycles(STAR,
			[{**CYCLE[0],"cyclic_order_proven":False}],PAIRS)[0]
		self.assertFalse(row["cyclic_order_proven"])

	def test_native_cycle_does_not_assign_owner(self):
		row=audit_vertex_star_face_cycles(STAR,CYCLE,PAIRS)[0]
		self.assertFalse(row["ownership_proven"])

if __name__=="__main__":
	unittest.main()
