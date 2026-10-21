import unittest
from scripts.cgal_endpoint_cycle_site_pairs import audit_endpoint_cycle_site_pairs

SITES={1:["P 0 0","S 0 0 1 0","S 0 0 0 1"],
	2:["P 0 0","S 0 0 0 1","S 0 0 -1 0"],
	3:["P 0 0","S 0 0 -1 0","S 0 0 0 -1"],
	4:["P 0 0","S 0 0 0 -1","S 0 0 1 0"]}
PAIRS={10:{"face_id":1,"neighbor_face_id":2},
	11:{"face_id":3,"neighbor_face_id":4},
	12:{"face_id":2,"neighbor_face_id":3},
	13:{"face_id":4,"neighbor_face_id":1}}
def vertices(pairs=PAIRS,sites=SITES):
	return {eid:{"face_ids":[p["face_id"],p["neighbor_face_id"]],
		"raw_slots":[str(fid)+" "+" ".join(f"{i}:{site}"
			for i,site in enumerate(sites[fid])) for fid in (p["face_id"],p["neighbor_face_id"])]}
		for eid,p in pairs.items()}
STAR={"status":"native_incident_star_unordered_only","ownership_proven":False,
	"point_site":{"kind":"P","coordinates":[0,0]},
	"edge_ids":[10,11],"incident_edges":[{"edge_id":e} for e in PAIRS]}
CYCLE={"status":"complete_native_face_cycle_only","cyclic_order_proven":True,
	"ownership_proven":False,"face_cycle":[1,2,3,4]}


class CycleSitePairTests(unittest.TestCase):
	def test_shared_original_sites_are_not_voronoi_owners(self):
		result=audit_endpoint_cycle_site_pairs([STAR],[CYCLE],PAIRS,vertices())[0]
		self.assertEqual(result["status"],"native_cycle_shared_sites_verified_only")
		self.assertEqual(len(result["adjacent_face_sites"]),4)
		self.assertFalse(result["ownership_proven"])

	def test_numeric_coordinate_format_does_not_change_site_identity(self):
		formatted={fid:[site.replace("P 0 0","P 0.0 0.00")
			for site in sites] for fid,sites in SITES.items()}
		result=audit_endpoint_cycle_site_pairs([STAR],[CYCLE],PAIRS,vertices(sites=formatted))[0]
		self.assertEqual(result["status"],"native_cycle_shared_sites_verified_only")

	def test_nonmatching_vertex_site_blocks(self):
		bad=dict(SITES)
		bad[3]=["P 0 0","S 9 9 8 8","S 0 0 0 -1"]
		result=audit_endpoint_cycle_site_pairs([STAR],[CYCLE],PAIRS,vertices(sites=bad))[0]
		self.assertEqual(result["status"],"blocked_cycle_shared_site_mismatch")

	def test_incomplete_cycle_blocks(self):
		result=audit_endpoint_cycle_site_pairs([STAR],[{**CYCLE,"face_cycle":[1,2,3]}],PAIRS,vertices())[0]
		self.assertEqual(result["status"],"blocked_cycle_shared_site_mismatch")

	def test_ownership_claim_blocks(self):
		result=audit_endpoint_cycle_site_pairs([STAR],[{**CYCLE,"ownership_proven":True}],PAIRS,vertices())[0]
		self.assertEqual(result["status"],"blocked_cycle_shared_site_mismatch")

if __name__=="__main__":
	unittest.main()
