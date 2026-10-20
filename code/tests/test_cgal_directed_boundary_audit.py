import unittest

from shapely.geometry import LineString,box

from scripts.cgal_directed_boundary_audit import directed_face_edges,audit_boundary_sides


A=("P",(0.,0.))
B=("S",(0.,0.,1000.,1000.))


class DirectedBoundaryTests(unittest.TestCase):
	def test_shared_edge_is_oriented_and_has_neighbor(self):
		left=box(0,0,1,1)
		right=box(1,0,2,1)
		data=directed_face_edges([left,right],[None,A],
			[(LineString([(1,1),(1,0)]),(A,B))],face_ids=[0])
		self.assertEqual(data[0]["total_edges"],1)
		edge=data[0]["reported_edges"][0]
		self.assertEqual(edge["start"],[1.,0.])
		self.assertEqual(edge["end"],[1.,1.])
		self.assertEqual(edge["role"],"PS")
		self.assertEqual(edge["neighbor_faces"][0]["face_index"],1)

	def test_window_boundary_has_no_neighbor(self):
		data=directed_face_edges([box(0,0,1,1)],[None],
			[(LineString([(0,0),(1,0)]),(A,B))])
		self.assertEqual(data[0]["without_neighbor"],1)

	def test_left_right_known_neighbor_membership(self):
		left=box(0,0,1,1)
		right=box(1,0,2,1)
		segments=[(LineString([(1,0),(1,1)]),(A,B))]
		result=audit_boundary_sides([left,right],[None,A],segments,
			face_ids=[0])
		self.assertEqual(result[0]["known_neighbor_checks"],1)
		self.assertEqual(result[0]["neighbor_label_mismatches"],0)
		result=audit_boundary_sides([left,right],[None,("P",(20.,20.))],
			segments,face_ids=[0])
		self.assertEqual(result[0]["neighbor_label_mismatches"],1)

	def test_invalid_input_is_rejected(self):
		with self.assertRaises(ValueError):
			directed_face_edges([box(0,0,1,1)],[],[])


if __name__=="__main__":
	unittest.main()
