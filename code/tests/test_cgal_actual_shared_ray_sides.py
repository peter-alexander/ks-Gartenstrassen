import unittest
from shapely.geometry import box
from scripts.cgal_actual_shared_ray_sides import audit_actual_shared_ray_sides

A=("P",(0.,0.))
B=("P",(1000.,0.))

class ActualSharedRaySideTests(unittest.TestCase):
	def test_two_faces_share_forward_ray(self):
		faces=[box(0,0,1,1),box(0,-1,1,0)]
		result=audit_actual_shared_ray_sides(faces,[A,B],
			[(0,(A,B),[])],{0:[[0.,0.,1.,0.]]},box(-1,-2,2,2))
		self.assertEqual(len(result),1)
		self.assertTrue(result[0]["locally_verified"])
		self.assertTrue(result[0]["left_site_is_first"])
		self.assertEqual(result[0]["on_forward_ray_m"],1)

	def test_only_point_contact_is_not_a_shared_boundary(self):
		faces=[box(0,0,1,1),box(1,1,2,2)]
		result=audit_actual_shared_ray_sides(faces,[A,B],
			[(0,(A,B),[])],{0:[[0.,1.,1.,1.]]},box(-1,-1,3,3))
		self.assertEqual(result,[])

if __name__=="__main__":
	unittest.main()
