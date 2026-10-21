import unittest
from scripts.cgal_endpoint_cw_ccw_cycle_alignment import audit_endpoint_cw_ccw_cycle_alignment

D={"status":"native_cycle_dual_incidence_only","edge_ids":[25,26],
	"ownership_proven":False,"voronoi_side_proven":False,
	"cycle_links":[{"edge_id":25,"dual_kind":"degenerate_endpoint",
		"cycle_forward_matches_export":False},
		{"edge_id":None,"dual_kind":"unexported_infinite_link"},
		{"edge_id":26,"dual_kind":"degenerate_endpoint",
			"cycle_forward_matches_export":True},
		{"edge_id":28,"dual_kind":"degenerate_endpoint",
			"cycle_forward_matches_export":False}]}
C={"status":"native_endpoint_cw_ccw_pair_recorded_only","edge_ids":[25,26],
	"ownership_proven":False,"voronoi_side_proven":False,
	"native_pairs":[{"edge_id":i,"cw_site":["P",20,10],
		"ccw_site":["S",20,10,20,20]} for i in [25,26,28]]}

class NativeCwCcwCycleAlignmentTests(unittest.TestCase):
	def test_link_orientation_keeps_sides_unproven(self):
		row=audit_endpoint_cw_ccw_cycle_alignment([D],[C])[0]
		self.assertEqual(row["status"],"native_cw_ccw_cycle_alignment_only")
		self.assertEqual([x["cycle_forward_matches_export"] for x in row["ordered_links"]],
			[False,True,False])
		self.assertFalse(row["voronoi_side_proven"])
		self.assertFalse(row["ownership_proven"])

	def test_nonendpoint_link_blocks(self):
		bad={**D,"cycle_links":[{**D["cycle_links"][0],
			"dual_kind":"non_endpoint"},*D["cycle_links"][1:]]}
		self.assertEqual(audit_endpoint_cw_ccw_cycle_alignment([bad],[C])[0]["status"],
			"blocked_cw_ccw_cycle_alignment")

	def test_missing_site_pair_blocks(self):
		bad={**C,"native_pairs":C["native_pairs"][:2]}
		self.assertEqual(audit_endpoint_cw_ccw_cycle_alignment([D],[bad])[0]["status"],
			"blocked_cw_ccw_cycle_alignment")

	def test_side_proof_claim_blocks(self):
		self.assertEqual(audit_endpoint_cw_ccw_cycle_alignment([D],
			[{**C,"voronoi_side_proven":True}])[0]["status"],
			"blocked_cw_ccw_cycle_alignment")

	def test_group_mismatch_blocks(self):
		with self.assertRaises(ValueError):
			audit_endpoint_cw_ccw_cycle_alignment([D],[])

if __name__=="__main__":
	unittest.main()
