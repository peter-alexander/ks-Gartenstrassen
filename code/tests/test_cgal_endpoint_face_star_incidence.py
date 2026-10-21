import unittest
from scripts.cgal_endpoint_face_star_incidence import audit_endpoint_face_star_incidence

S={"status":"native_incident_star_unordered_only","ownership_proven":False,
	"cyclic_order_proven":False,"edge_ids":[18,22],
	"incident_edges":[{"edge_id":18},{"edge_id":22},{"edge_id":30}]}
C={"status":"native_face_chain_confirmed_not_ownership","ownership_proven":False,
	"cyclic_order_proven":False,"edge_ids":[18,22],"third_edge_id":30,
	"shared_with_third":[{"edge_id":18,"face_id":2},{"edge_id":22,"face_id":3}]}
F={18:{"face_id":1,"neighbor_face_id":2},
	22:{"face_id":3,"neighbor_face_id":4},
	30:{"face_id":2,"neighbor_face_id":3}}


class FaceStarIncidenceTests(unittest.TestCase):
	def test_native_incidence_is_not_rotation_or_ownership(self):
		row=audit_endpoint_face_star_incidence([S],[C],F)[0]
		self.assertEqual(row["status"],"native_face_star_incidence_checked_only")
		self.assertFalse(row["cyclic_order_proven"])
		self.assertFalse(row["ownership_proven"])

	def test_wrong_shared_face_blocks(self):
		bad={**C,"shared_with_third":[{"edge_id":18,"face_id":1},C["shared_with_third"][1]]}
		self.assertEqual(audit_endpoint_face_star_incidence([S],[bad],F)[0]["status"],
			"blocked_face_star_incidence_mismatch")

	def test_extra_incident_edge_blocks(self):
		bad={**S,"incident_edges":[*S["incident_edges"],{"edge_id":31}]}
		self.assertEqual(audit_endpoint_face_star_incidence([bad],[C],F)[0]["status"],
			"blocked_face_star_incidence_mismatch")

	def test_missing_face_pair_blocks(self):
		self.assertEqual(audit_endpoint_face_star_incidence([S],[C],{18:F[18],22:F[22]})[0]["status"],
			"blocked_face_star_incidence_mismatch")

	def test_mismatched_counts_rejected(self):
		with self.assertRaises(ValueError):
			audit_endpoint_face_star_incidence([S],[],F)


if __name__=="__main__":
	unittest.main()
