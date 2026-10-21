import unittest
from scripts.cgal_endpoint_cycle_coverage import audit_endpoint_cycle_coverage

def star(ids,third):
	return {"status":"native_incident_star_unordered_only","ownership_proven":False,
		"edge_ids":ids,"incident_edges":[{"edge_id":i} for i in [*ids,third]]}

def cycle(ids,path):
	return {"status":"complete_native_face_cycle_only","cyclic_order_proven":True,
		"ownership_proven":False,"edge_ids":ids,"face_cycle":path}

STARS=[star([25,26],28),star([18,22],30)]
CYCLES=[cycle([25,26],[21,22,31,29]),cycle([18,22],[2,15,30,25])]

class EndpointCycleCoverageTests(unittest.TestCase):
	def test_both_complete_cycles_are_not_ownership(self):
		result=audit_endpoint_cycle_coverage(STARS,CYCLES)
		self.assertTrue(all(x["cyclic_order_proven"] and not x["ownership_proven"] for x in result))
		self.assertTrue(all(x["status"]=="native_four_face_cycle_observed_no_ownership" for x in result))

	def test_short_cycle_blocks(self):
		result=audit_endpoint_cycle_coverage(STARS,[cycle([25,26],[21,22,31]),CYCLES[1]])
		self.assertEqual(result[0]["status"],"blocked_incomplete_native_cycle_coverage")

	def test_duplicate_face_blocks(self):
		result=audit_endpoint_cycle_coverage(STARS,[cycle([25,26],[21,22,31,31]),CYCLES[1]])
		self.assertEqual(result[0]["status"],"blocked_incomplete_native_cycle_coverage")

	def test_ownership_claim_blocks(self):
		result=audit_endpoint_cycle_coverage(STARS,[{**CYCLES[0],"ownership_proven":True},CYCLES[1]])
		self.assertEqual(result[0]["status"],"blocked_incomplete_native_cycle_coverage")

	def test_missing_group_blocks(self):
		with self.assertRaises(ValueError):
			audit_endpoint_cycle_coverage(STARS,CYCLES[:1])

if __name__=="__main__":
	unittest.main()
