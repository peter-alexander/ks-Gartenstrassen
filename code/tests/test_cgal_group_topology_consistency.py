import unittest
from scripts.cgal_group_topology_consistency import audit_group_topological_consistency

A={"kind":"S","coordinates":[0,0,0,10]}
B={"kind":"S","coordinates":[0,-10,0,0]}
GROUP={"status":"grouped_diagnostic_only","edge_ids":[3,4],
	"left_segment":A,"right_segment":B}
LOCAL={"native_edges":[{"edge_id":3},{"edge_id":4}],
	"left_face":1,"right_face":2,"candidate_left":A,"candidate_right":B}
NEIGHBORS=[
	{"face_index":1,"known_neighbor_constraints":2,
		"known_neighbor_mismatches":0,"unknown_neighbor_constraints":0},
	{"face_index":2,"known_neighbor_constraints":2,
		"known_neighbor_mismatches":0,"unknown_neighbor_constraints":0}]

class GroupTopologyConsistencyTests(unittest.TestCase):
	def test_matching_evidence_does_not_prove_ownership(self):
		result=audit_group_topological_consistency([GROUP],[LOCAL],NEIGHBORS)
		self.assertEqual(result[0]["status"],"consistent_but_ownership_unproven")
		self.assertFalse(result[0]["ownership_proven"])
		self.assertEqual(result[0]["known_neighbor_constraints"],4)

	def test_swapped_sites_fail_closed(self):
		group={**GROUP,"left_segment":B,"right_segment":A}
		result=audit_group_topological_consistency([group],[LOCAL],NEIGHBORS)
		self.assertEqual(result[0]["status"],"blocked_group_side_candidate_mismatch")

	def test_proven_neighbor_conflict_fails_closed(self):
		neighbors=[{**NEIGHBORS[0],"known_neighbor_mismatches":1},NEIGHBORS[1]]
		result=audit_group_topological_consistency([GROUP],[LOCAL],neighbors)
		self.assertEqual(result[0]["status"],"blocked_proven_neighbor_conflict")

	def test_missing_local_evidence_fails_closed(self):
		result=audit_group_topological_consistency([GROUP],[],NEIGHBORS)
		self.assertEqual(result[0]["status"],"blocked_missing_or_rejected_native_group")

	def test_missing_neighbor_fails_closed(self):
		result=audit_group_topological_consistency([GROUP],[LOCAL],NEIGHBORS[:1])
		self.assertEqual(result[0]["status"],"blocked_missing_neighbor_audit")

	def test_duplicate_group_is_rejected(self):
		with self.assertRaises(ValueError):
			audit_group_topological_consistency([GROUP,GROUP],[LOCAL],NEIGHBORS)

if __name__=="__main__":
	unittest.main()
