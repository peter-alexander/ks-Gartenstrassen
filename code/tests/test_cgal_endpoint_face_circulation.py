import unittest
from scripts.cgal_endpoint_face_circulation import audit_endpoint_face_circulation

S={"status":"native_incident_star_unordered_only","ownership_proven":False,
	"edge_ids":[18,22]}
V={"status":"native_point_vertex_slots_observed_only","ownership_proven":False,
	"face_vertex_slots":[{"face_id":1,"vertex_slot":0},
		{"face_id":2,"vertex_slot":0},{"face_id":3,"vertex_slot":0}]}
N={"faces":{1:[9,2,3],2:[9,3,1],3:[9,1,2]}}


class FaceCirculationTests(unittest.TestCase):
	def test_complete_native_cycle_no_generator_promotion(self):
		row=audit_endpoint_face_circulation([S],[V],N)[0]
		self.assertEqual(row["status"],"complete_native_face_cycle_only")
		self.assertEqual(row["face_cycle"],[1,2,3])
		self.assertTrue(row["cyclic_order_proven"])
		self.assertFalse(row["ownership_proven"])

	def test_missing_face_blocks(self):
		bad={"faces":{1:N["faces"][1],2:N["faces"][2]}}
		self.assertEqual(audit_endpoint_face_circulation([S],[V],bad)[0]["status"],
			"blocked_incomplete_or_ambiguous_face_circulation")

	def test_missing_vertex_star_face_blocks(self):
		bad={"faces":{**N["faces"],1:[9,2,8]}}
		self.assertEqual(audit_endpoint_face_circulation([S],[V],bad)[0]["status"],
			"blocked_incomplete_or_ambiguous_face_circulation")

	def test_ownership_claim_blocks(self):
		self.assertEqual(audit_endpoint_face_circulation([{**S,"ownership_proven":True}],[V],N)[0]["status"],
			"blocked_incomplete_or_ambiguous_face_circulation")

if __name__=="__main__":
	unittest.main()
