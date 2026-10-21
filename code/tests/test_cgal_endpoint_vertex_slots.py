import unittest
from scripts.cgal_endpoint_vertex_slots import audit_endpoint_vertex_slots

STAR={"status":"native_incident_star_unordered_only","ownership_proven":False,
	"cyclic_order_proven":False,"edge_ids":[1,2],
	"point_site":{"kind":"P","coordinates":[0,0]},
	"incident_edges":[{"edge_id":1},{"edge_id":2},{"edge_id":3}]}
PAIRS={1:{"face_id":1,"neighbor_face_id":2},
	2:{"face_id":2,"neighbor_face_id":3},
	3:{"face_id":3,"neighbor_face_id":1}}
SITE="0:P 0 0 1:S 0 0 10 0 2:INF"
VERTICES={e:{"face_ids":[p["face_id"],p["neighbor_face_id"]],
	"raw_slots":[f'{p["face_id"]} {SITE}',f'{p["neighbor_face_id"]} {SITE}']}
	for e,p in PAIRS.items()}


class PointVertexSlotTests(unittest.TestCase):
	def test_unique_point_site_slot_does_not_prove_rotation(self):
		row=audit_endpoint_vertex_slots([STAR],PAIRS,VERTICES)[0]
		self.assertEqual(row["status"],"native_point_vertex_slots_observed_only")
		self.assertEqual(len(row["face_vertex_slots"]),3)
		self.assertFalse(row["cyclic_order_proven"])
		self.assertFalse(row["ownership_proven"])

	def test_wrong_vertex_site_blocks(self):
		bad={**VERTICES,3:{**VERTICES[3],"raw_slots":[
			VERTICES[3]["raw_slots"][0].replace("P 0 0","P 9 9"),
			VERTICES[3]["raw_slots"][1]]}}
		self.assertEqual(audit_endpoint_vertex_slots([STAR],PAIRS,bad)[0]["status"],
			"blocked_ambiguous_or_missing_point_vertex_slot")

	def test_missing_edge_blocks(self):
		self.assertEqual(audit_endpoint_vertex_slots([STAR],PAIRS,{1:VERTICES[1],2:VERTICES[2]})[0]["status"],
			"blocked_ambiguous_or_missing_point_vertex_slot")

	def test_invalid_proof_claim_blocks(self):
		self.assertEqual(audit_endpoint_vertex_slots([{**STAR,"ownership_proven":True}],PAIRS,VERTICES)[0]["status"],
			"blocked_ambiguous_or_missing_point_vertex_slot")

if __name__=="__main__":
	unittest.main()
