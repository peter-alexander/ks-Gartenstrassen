import unittest
from scripts.cgal_endpoint_opposite_slots import audit_endpoint_primal_opposite_slots

S={"status":"native_incident_star_unordered_only","edge_ids":[1,2],
	"ownership_proven":False,"cyclic_order_proven":False,
	"incident_edges":[{"edge_id":1},{"edge_id":2},{"edge_id":3}]}
V={"status":"native_point_vertex_slots_observed_only","edge_ids":[1,2],
	"ownership_proven":False,"cyclic_order_proven":False,
	"face_vertex_slots":[{"face_id":10,"vertex_slot":0},
		{"face_id":11,"vertex_slot":1},{"face_id":12,"vertex_slot":2}]}
F={1:{"face_id":10,"neighbor_face_id":11},
	2:{"face_id":11,"neighbor_face_id":12},
	3:{"face_id":12,"neighbor_face_id":10}}
I={1:{"local_index":1,"neighbor_index":2},
	2:{"local_index":0,"neighbor_index":0},
	3:{"local_index":0,"neighbor_index":2}}


class NativePointOppositeSlotTests(unittest.TestCase):
	def test_point_is_on_primal_edges_not_opposite(self):
		row=audit_endpoint_primal_opposite_slots([S],[V],F,I)[0]
		self.assertEqual(row["status"],"native_point_on_primal_edge_checked_only")
		self.assertEqual(len(row["checked_incidence"]),6)
		self.assertFalse(row["cyclic_order_proven"])
		self.assertFalse(row["ownership_proven"])

	def test_point_as_opposite_vertex_rejected(self):
		bad={**I,1:{"local_index":0,"neighbor_index":2}}
		self.assertEqual(audit_endpoint_primal_opposite_slots([S],[V],F,bad)[0]["status"],
			"blocked_point_opposite_slot_conflict")

	def test_missing_face_slot_rejected(self):
		bad={**V,"face_vertex_slots":V["face_vertex_slots"][:2]}
		self.assertEqual(audit_endpoint_primal_opposite_slots([S],[bad],F,I)[0]["status"],
			"blocked_point_opposite_slot_conflict")

	def test_ownership_claim_rejected(self):
		self.assertEqual(audit_endpoint_primal_opposite_slots([S],[{**V,"ownership_proven":True}],F,I)[0]["status"],
			"blocked_point_opposite_slot_conflict")

	def test_mismatched_groups_rejected(self):
		with self.assertRaises(ValueError):
			audit_endpoint_primal_opposite_slots([S],[],F,I)


if __name__=="__main__":
	unittest.main()
