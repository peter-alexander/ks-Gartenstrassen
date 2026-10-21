import unittest
from scripts.cgal_endpoint_native_vertex_stars import audit_endpoint_native_vertex_stars

VERTICES={10:("P",(0.,10.)),2:("S",(0.,0.,0.,10.)),
	9:("S",(0.,10.,0.,20.)),4:("S",(0.,10.,10.,10.))}
EDGES={18:(9,10),22:(10,2),30:(10,4)}
ROWS=[{"shared_native_vertex_id":10,"source_vertex_evidence":[
	{"edge_id":18},{"edge_id":22}]}]

class NativeEndpointVertexStarTests(unittest.TestCase):
	def test_complete_star_includes_third_edge_without_owner(self):
		row=audit_endpoint_native_vertex_stars(ROWS,VERTICES,EDGES)[0]
		self.assertEqual([x["edge_id"] for x in row["incident_native_edges"]],[18,22,30])
		self.assertEqual(row["unresolved_ray_edge_ids"],[18,22])
		self.assertFalse(row["ownership_proven"])
		self.assertFalse(row["cyclic_order_proven"])

	def test_missing_native_ray_rejected(self):
		with self.assertRaises(ValueError):
			audit_endpoint_native_vertex_stars(ROWS,VERTICES,{18:(9,10)})

	def test_missing_neighbor_rejected(self):
		with self.assertRaises(ValueError):
			audit_endpoint_native_vertex_stars(ROWS,VERTICES,{**EDGES,31:(10,99)})

	def test_non_point_center_rejected(self):
		with self.assertRaises(ValueError):
			audit_endpoint_native_vertex_stars(ROWS,{**VERTICES,10:VERTICES[9]},EDGES)

	def test_unrelated_edges_are_not_in_star(self):
		row=audit_endpoint_native_vertex_stars(ROWS,
			{**VERTICES,7:("P",(20.,20.))},{**EDGES,44:(2,7)})[0]
		self.assertEqual(len(row["incident_native_edges"]),3)

if __name__=="__main__":
	unittest.main()
