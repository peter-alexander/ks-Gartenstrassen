import unittest
from scripts.cgal_group_topology_consistency import audit_group_topological_consistency

A={"kind":"S","coordinates":[0,0,0,10]}
B={"kind":"S","coordinates":[0,-10,0,0]}
GROUP={"status":"grouped_diagnostic_only","edge_ids":[3,4],
	"left_segment":A,"right_segment":B,"ownership_proven":False}
LOCAL={"native_edges":[{"edge_id":3},{"edge_id":4}],
	"left_face":1,"right_face":2,"candidate_left":A,"candidate_right":B,
	"ownership_proven":False}
NEIGHBORS=[
	{"face_index":1,"candidate_site":A,"known_neighbor_constraints":2,
		"known_neighbor_mismatches":0,"unknown_neighbor_constraints":0,
		"endpoint_edge_fragments":2,"endpoint_candidate_conflicts":1,
		"known_checks":[{"exact_pair":True},{"exact_pair":True}],
		"unknown_checks":[],
		"endpoint_checks":[{"contains_candidate":True},{"contains_candidate":False}]},
	{"face_index":2,"candidate_site":B,"known_neighbor_constraints":2,
		"known_neighbor_mismatches":0,"unknown_neighbor_constraints":0,
		"endpoint_edge_fragments":2,"endpoint_candidate_conflicts":1,
		"known_checks":[{"exact_pair":True},{"exact_pair":True}],
		"unknown_checks":[],
		"endpoint_checks":[{"contains_candidate":True},{"contains_candidate":False}]}]


def audit(groups=None,local=None,neighbors=None):
	return audit_group_topological_consistency(
		[GROUP] if groups is None else groups,
		[LOCAL] if local is None else local,
		NEIGHBORS if neighbors is None else neighbors)


class GroupTopologyConsistencyTests(unittest.TestCase):
	def test_regular_agreement_and_endpoint_conflicts_are_separate(self):
		result=audit()[0]
		self.assertEqual(result["status"],
			"regular_neighbors_consistent_endpoint_ambiguous")
		self.assertEqual(result["known_neighbor_constraints"],4)
		self.assertEqual(result["known_neighbor_mismatches"],0)
		self.assertEqual(result["endpoint_edge_fragments"],4)
		self.assertEqual(result["endpoint_candidate_conflicts"],2)
		self.assertFalse(result["ownership_proven"])

	def test_swapped_sites_fail_closed(self):
		result=audit(groups=[{**GROUP,"left_segment":B,"right_segment":A}])
		self.assertEqual(result[0]["status"],"blocked_group_side_candidate_mismatch")

	def test_proven_neighbor_conflict_fails_closed(self):
		first={**NEIGHBORS[0],"known_neighbor_mismatches":1,
			"known_checks":[{"exact_pair":False},{"exact_pair":True}]}
		result=audit(neighbors=[first,NEIGHBORS[1]])
		self.assertEqual(result[0]["status"],"blocked_proven_neighbor_conflict")

	def test_missing_local_evidence_fails_closed(self):
		self.assertEqual(audit(local=[])[0]["status"],
			"blocked_missing_or_rejected_native_group")

	def test_missing_neighbor_fails_closed(self):
		self.assertEqual(audit(neighbors=NEIGHBORS[:1])[0]["status"],
			"blocked_missing_neighbor_audit")

	def test_neighbor_candidate_mismatch_fails_closed(self):
		result=audit(neighbors=[{**NEIGHBORS[0],"candidate_site":B},NEIGHBORS[1]])
		self.assertEqual(result[0]["status"],"blocked_neighbor_candidate_mismatch")

	def test_known_neighbor_summary_without_checks_is_rejected(self):
		result=audit(neighbors=[{**NEIGHBORS[0],"known_checks":[]},NEIGHBORS[1]])
		self.assertEqual(result[0]["status"],"blocked_inconsistent_neighbor_evidence")

	def test_endpoint_conflict_summary_must_match_checks(self):
		result=audit(neighbors=[{**NEIGHBORS[0],"endpoint_candidate_conflicts":0},
			NEIGHBORS[1]])
		self.assertEqual(result[0]["status"],"blocked_inconsistent_neighbor_evidence")

	def test_no_regular_neighbors_does_not_count_as_consistent(self):
		first={**NEIGHBORS[0],"known_neighbor_constraints":0,"known_checks":[]}
		result=audit(neighbors=[first,NEIGHBORS[1]])
		self.assertEqual(result[0]["status"],
			"blocked_insufficient_regular_neighbor_evidence")

	def test_no_endpoint_evidence_does_not_count_as_consistent(self):
		first={**NEIGHBORS[0],"endpoint_edge_fragments":0,
			"endpoint_candidate_conflicts":0,"endpoint_checks":[]}
		result=audit(neighbors=[first,NEIGHBORS[1]])
		self.assertEqual(result[0]["status"],"blocked_missing_endpoint_evidence")

	def test_unknown_neighbor_blocks_consistency(self):
		first={**NEIGHBORS[0],"unknown_neighbor_constraints":1,
			"unknown_checks":[{"neighbor_face":10}]}
		result=audit(neighbors=[first,NEIGHBORS[1]])
		self.assertEqual(result[0]["status"],"blocked_unknown_neighbor")

	def test_reused_local_face_is_rejected(self):
		result=audit(local=[{**LOCAL,"right_face":1}])
		self.assertEqual(result[0]["status"],"blocked_invalid_local_face_pair")

	def test_unexpected_proof_promotion_is_rejected(self):
		result=audit(groups=[{**GROUP,"ownership_proven":True}])
		self.assertEqual(result[0]["status"],"blocked_unexpected_proof_claim")

	def test_duplicate_group_is_rejected(self):
		with self.assertRaises(ValueError):
			audit(groups=[GROUP,GROUP])

	def test_overlapping_group_is_rejected(self):
		another={**GROUP,"edge_ids":[4,5]}
		with self.assertRaises(ValueError):
			audit(groups=[GROUP,another])

	def test_duplicate_neighbor_audit_is_rejected(self):
		with self.assertRaises(ValueError):
			audit(neighbors=[*NEIGHBORS,NEIGHBORS[0]])


if __name__=="__main__":
	unittest.main()
