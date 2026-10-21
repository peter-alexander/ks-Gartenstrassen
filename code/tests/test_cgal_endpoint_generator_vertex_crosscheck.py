import unittest
from scripts.cgal_endpoint_generator_vertex_crosscheck import audit_endpoint_generator_vertex_crosscheck

C={"kind":"S","coordinates":[20,0,20,10]}
P=("P",(20.,10.))
S=("S",(20.,0.,20.,10.))
T=("S",(20.,10.,20.,20.))
VERTICES={0:P,1:S,2:T}
IDS={25:(0,2),26:(0,1)}
ROWS=[{"face_index":1,"candidate_site":C,
	"status":"coincident_endpoint_conflict_isolated_not_resolved",
	"matching_endpoint_sources":[{"edge_id":26}],
	"conflicting_endpoint_sources":[{"edge_id":25}]}]


class EndpointGeneratorVertexCrosscheckTests(unittest.TestCase):
	def test_shared_endpoint_is_original_vertex(self):
		row=audit_endpoint_generator_vertex_crosscheck(ROWS,VERTICES,IDS)[0]
		self.assertEqual(row["shared_native_vertex_id"],0)
		self.assertEqual(row["source_vertex_evidence"][0]["candidate_vertex_id"],1)
		self.assertFalse(row["ownership_proven"])

	def test_missing_edge_rejected(self):
		with self.assertRaises(ValueError):
			audit_endpoint_generator_vertex_crosscheck(ROWS,VERTICES,{25:(0,2)})

	def test_wrong_matching_vertex_rejected(self):
		with self.assertRaises(ValueError):
			audit_endpoint_generator_vertex_crosscheck(ROWS,VERTICES,{25:(0,2),26:(0,2)})

	def test_different_common_vertex_rejected(self):
		v={**VERTICES,3:("P",(0.,0.))}
		with self.assertRaises(ValueError):
			audit_endpoint_generator_vertex_crosscheck(ROWS,v,{25:(3,2),26:(0,1)})

	def test_unclassified_conflict_rejected(self):
		with self.assertRaises(ValueError):
			audit_endpoint_generator_vertex_crosscheck(
				[{**ROWS[0],"status":"blocked"}],VERTICES,IDS)

if __name__=="__main__":
	unittest.main()
