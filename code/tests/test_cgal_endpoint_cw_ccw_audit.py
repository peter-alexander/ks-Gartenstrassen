import unittest
from scripts.cgal_endpoint_cw_ccw_audit import audit_endpoint_cw_ccw_pairs

P=("P",(0.0,0.0))
SITES=[("S",(0.0,0.0,0.0,10.0)),
	("S",(0.0,0.0,10.0,0.0)),
	("S",(0.0,-10.0,0.0,0.0))]
EDGES=[(i,(P,SITES[i]),[]) for i in range(3)]
LINES=[f"T {i} 1 CW P 0 0 | CCW S "+
	" ".join(str(x) for x in site[1])
	for i,site in enumerate(SITES)]
STAR={"status":"native_incident_star_unordered_only",
	"ownership_proven":False,"edge_ids":[0,1],
	"incident_edges":[{"edge_id":i} for i in range(3)]}
DUAL={"status":"native_cycle_dual_incidence_only",
	"ownership_proven":False,"voronoi_side_proven":False,
	"cycle_links":[{"edge_id":0},{"edge_id":1},{"edge_id":2},
		{"edge_id":None}]}


class EndpointCwCcwAuditTests(unittest.TestCase):
	def test_original_cw_ccw_pairs_are_not_side_proof(self):
		row=audit_endpoint_cw_ccw_pairs([STAR],[DUAL],LINES,EDGES)[0]
		self.assertEqual(row["status"],"native_endpoint_cw_ccw_pair_recorded_only")
		self.assertEqual(len(row["native_pairs"]),3)
		self.assertFalse(row["voronoi_side_proven"])
		self.assertFalse(row["ownership_proven"])

	def test_wrong_native_site_blocks(self):
		bad=list(LINES)
		bad[1]=bad[1].replace("S 0.0 0.0 10.0 0.0","S 9 9 10 0")
		self.assertEqual(audit_endpoint_cw_ccw_pairs([STAR],[DUAL],bad,EDGES)[0]["status"],
			"blocked_endpoint_cw_ccw_pair_mismatch")

	def test_missing_topology_blocks(self):
		self.assertEqual(audit_endpoint_cw_ccw_pairs([STAR],[DUAL],LINES[:2],EDGES)[0]["status"],
			"blocked_endpoint_cw_ccw_pair_mismatch")

	def test_nonendpoint_dual_blocks(self):
		bad=list(LINES)
		bad[0]=bad[0].replace("T 0 1 CW","T 0 0 CW")
		self.assertEqual(audit_endpoint_cw_ccw_pairs([STAR],[DUAL],bad,EDGES)[0]["status"],
			"blocked_endpoint_cw_ccw_pair_mismatch")

	def test_unexpected_side_proof_blocks(self):
		self.assertEqual(audit_endpoint_cw_ccw_pairs([STAR],
			[{**DUAL,"voronoi_side_proven":True}],LINES,EDGES)[0]["status"],
			"blocked_endpoint_cw_ccw_pair_mismatch")


if __name__=="__main__":
	unittest.main()
