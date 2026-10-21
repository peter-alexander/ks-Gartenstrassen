import unittest
from scripts.cgal_unresolved_endpoint_conflicts import audit_unresolved_endpoint_conflicts

SITE={"kind":"S","coordinates":[20,0,20,10]}
OTHER={"kind":"S","coordinates":[20,10,20,20]}
POINT={"kind":"P","coordinates":[20,10]}
CAND=[{"face_index":1,"status":"candidate_only_not_proven",
	"candidate_site":SITE,"endpoint_conflicting_pairs":1}]
CENSUS=[{"face_index":1,"ownership_proven":False,
	"boundary_source_records":[
		{"edge_id":25,"primitive_kind":"R","intersection_length_m":5,
			"sites":[POINT,OTHER]},
		{"edge_id":26,"primitive_kind":"R","intersection_length_m":5,
			"sites":[POINT,SITE]}]}]
STAR=[{"status":"native_incident_star_unordered_only",
	"edge_ids":[25,26],"ownership_proven":False}]
ZERO=[{"status":"native_coincident_rays_zero_third_dual_only",
	"ownership_proven":False}]

class EndpointConflictTraceTests(unittest.TestCase):
	def test_conflict_is_not_ownership_proof(self):
		row=audit_unresolved_endpoint_conflicts(CAND,CENSUS,STAR,ZERO)[0]
		self.assertEqual(row["status"],"coincident_endpoint_conflict_isolated_not_resolved")
		self.assertEqual(row["conflicting_endpoint_sources"][0]["edge_id"],25)
		self.assertEqual(row["matching_endpoint_sources"][0]["edge_id"],26)
		self.assertFalse(row["ownership_proven"])

	def test_only_matching_source_blocks(self):
		census=[{**CENSUS[0],"boundary_source_records":CENSUS[0]["boundary_source_records"][1:]}]
		self.assertEqual(audit_unresolved_endpoint_conflicts(CAND,census,STAR,ZERO)[0]["status"],
			"blocked_or_unclassified_endpoint_conflict")

	def test_nonray_source_blocks(self):
		records=[{**CENSUS[0]["boundary_source_records"][0],"primitive_kind":"S"},
			CENSUS[0]["boundary_source_records"][1]]
		self.assertEqual(audit_unresolved_endpoint_conflicts(CAND,
			[{**CENSUS[0],"boundary_source_records":records}],STAR,ZERO)[0]["status"],
			"blocked_or_unclassified_endpoint_conflict")

	def test_unsupported_star_blocks(self):
		with self.assertRaises(ValueError):
			audit_unresolved_endpoint_conflicts(CAND,CENSUS,STAR,
				[{**ZERO[0],"ownership_proven":True}])

	def test_missing_face_blocks(self):
		with self.assertRaises(ValueError):
			audit_unresolved_endpoint_conflicts(CAND,[],STAR,ZERO)

if __name__=="__main__":
	unittest.main()
