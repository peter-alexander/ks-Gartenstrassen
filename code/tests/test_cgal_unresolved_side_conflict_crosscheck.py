import unittest
from scripts.cgal_unresolved_side_conflict_crosscheck import audit_unresolved_side_conflict_crosscheck

SITE_A={"kind":"S","coordinates":[20,10,20,20]}
SITE_B={"kind":"S","coordinates":[20,0,20,10]}
SIDES=[{"left_face":2,"right_face":1,"candidate_left":SITE_A,
	"candidate_right":SITE_B,"shared_forward_m":5,"ownership_proven":False,
	"native_edges":[{"edge_id":25,"candidate_on_left":True,
		"candidate_on_right":False},{"edge_id":26,"candidate_on_left":False,
		"candidate_on_right":True}]}]
CONFLICTS=[{"face_index":fid,"candidate_site":candidate,
	"status":"coincident_endpoint_conflict_isolated_not_resolved",
	"matching_endpoint_sources":[{"edge_id":yes,"intersection_length_m":5}],
	"conflicting_endpoint_sources":[{"edge_id":no,"intersection_length_m":5}],
	"ownership_proven":False}
	for fid,candidate,yes,no in [(2,SITE_A,25,26),(1,SITE_B,26,25)]]


class SideConflictCrosscheckTests(unittest.TestCase):
	def test_both_sides_consistent_without_ownership(self):
		row=audit_unresolved_side_conflict_crosscheck(SIDES,CONFLICTS)[0]
		self.assertEqual(row["status"],"geometric_sides_and_conflicts_consistent_only")
		self.assertEqual([x["geometric_side"] for x in row["face_evidence"]],["left","right"])
		self.assertFalse(row["ownership_proven"])

	def test_swapped_candidate_blocks(self):
		bad=[{**SIDES[0],"candidate_left":SITE_B}]
		self.assertEqual(audit_unresolved_side_conflict_crosscheck(bad,CONFLICTS)[0]["status"],
			"blocked_geometric_side_conflict_mismatch")

	def test_wrong_source_side_blocks(self):
		bad=[{**SIDES[0],"native_edges":[
			{**SIDES[0]["native_edges"][0],"candidate_on_left":False},
			SIDES[0]["native_edges"][1]]}]
		self.assertEqual(audit_unresolved_side_conflict_crosscheck(bad,CONFLICTS)[0]["status"],
			"blocked_geometric_side_conflict_mismatch")

	def test_uncovered_face_blocks(self):
		with self.assertRaises(ValueError):
			audit_unresolved_side_conflict_crosscheck([],CONFLICTS)

	def test_duplicate_conflict_blocks(self):
		with self.assertRaises(ValueError):
			audit_unresolved_side_conflict_crosscheck(SIDES,[*CONFLICTS,CONFLICTS[0]])

if __name__=="__main__":
	unittest.main()
