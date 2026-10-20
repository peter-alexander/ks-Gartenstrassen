import unittest
from shapely.geometry import box
from scripts.cgal_directed_side_calibration import audit_directed_side_calibration

A=("P",(0.,0.))
B=("P",(1000.,0.))

class DirectedSideCalibrationTests(unittest.TestCase):
	def test_two_proven_opposite_sides(self):
		faces=[box(0,0,1,1),box(0,-1,1,0)]
		labels=[A,B]
		rays={0:[[0.,0.,1.,0.]]}
		result=audit_directed_side_calibration(faces,labels,
			[(0,(A,B),[])],rays)
		self.assertEqual(len(result),1)
		self.assertTrue(result[0]["left_site_matches_first"])

	def test_unproven_face_is_not_calibration(self):
		faces=[box(0,0,1,1),box(0,-1,1,0)]
		result=audit_directed_side_calibration(faces,[A,None],
			[(0,(A,B),[])],{0:[[0.,0.,1.,0.]]})
		self.assertEqual(result,[])

if __name__=="__main__":
	unittest.main()
