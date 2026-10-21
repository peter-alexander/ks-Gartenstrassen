import unittest
from scripts.cgal_cycle_dual_incidence import audit_cycle_dual_incidence

STAR={"status":"native_incident_star_unordered_only","ownership_proven":False,
	"edge_ids":[25,26],"incident_edges":[{"edge_id":25},{"edge_id":26},{"edge_id":28}]}
CYCLE={"status":"native_cycle_shared_sites_verified_only","ownership_proven":False,
	"adjacent_face_sites":[
		{"face_ids":[1,2],"shared_other_site":["S",0,0,0,10]},
		{"face_ids":[2,3],"shared_other_site":["INF"]},
		{"face_ids":[3,4],"shared_other_site":["S",0,-10,0,0]},
		{"face_ids":[4,1],"shared_other_site":["S",0,0,10,0]}]}
PAIRS={25:{"face_id":1,"neighbor_face_id":2},
	26:{"face_id":3,"neighbor_face_id":4},
	28:{"face_id":4,"neighbor_face_id":1}}
INC={i:{"local_index":1,"neighbor_index":2} for i in PAIRS}

class NativeCycleDualIncidenceTests(unittest.TestCase):
	def test_exact_mapping_keeps_endpoint_distinction(self):
		row=audit_cycle_dual_incidence([STAR],[CYCLE],PAIRS,INC,{25,26})[0]
		self.assertEqual(row["status"],"native_cycle_dual_incidence_only")
		self.assertEqual([e["edge_id"] for e in row["cycle_links"]],[25,None,26,28])
		self.assertEqual(row["cycle_links"][0]["dual_kind"],"degenerate_endpoint")
		self.assertEqual(row["cycle_links"][3]["dual_kind"],"non_endpoint")
		self.assertFalse(row["ownership_proven"])
		self.assertFalse(row["voronoi_side_proven"])

	def test_original_immutable_infinity_site(self):
		cycle={**CYCLE,"adjacent_face_sites":[
			{**link,"shared_other_site":tuple(link["shared_other_site"])}
			for link in CYCLE["adjacent_face_sites"]]}
		row=audit_cycle_dual_incidence([STAR],[cycle],PAIRS,INC,{25,26})[0]
		self.assertEqual(row["status"],"native_cycle_dual_incidence_only")

	def test_ambiguous_face_pair_blocks(self):
		pairs={**PAIRS,99:PAIRS[25]}
		self.assertEqual(audit_cycle_dual_incidence([STAR],[CYCLE],pairs,INC,{25,26})[0]["status"],
			"blocked_cycle_dual_incidence")

	def test_infinite_link_must_not_be_exported(self):
		pairs={**PAIRS,99:{"face_id":2,"neighbor_face_id":3}}
		self.assertEqual(audit_cycle_dual_incidence([STAR],[CYCLE],pairs,INC,{25,26})[0]["status"],
			"blocked_cycle_dual_incidence")

	def test_missing_incidence_blocks(self):
		self.assertEqual(audit_cycle_dual_incidence([STAR],[CYCLE],PAIRS,{25:INC[25]}, {25,26})[0]["status"],
			"blocked_cycle_dual_incidence")

	def test_claimed_ownership_blocks(self):
		self.assertEqual(audit_cycle_dual_incidence([STAR],[{**CYCLE,"ownership_proven":True}],PAIRS,INC,{25,26})[0]["status"],
			"blocked_cycle_dual_incidence")

if __name__=="__main__":
	unittest.main()
