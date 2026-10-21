import unittest
from shapely.geometry import box
from scripts.cgal_coincident_ray_distance_witness import audit_coincident_ray_distance_witness

POLYGONS=[box(0,0,10,5),box(0,5,10,10)]
SITES=[{"kind":"S","coordinates":[0,10000,10000,10000]},
	{"kind":"S","coordinates":[0,0,10000,0]}]
SIDE={"left_face":1,"right_face":0,"candidate_left":SITES[0],
	"candidate_right":SITES[1],"ownership_proven":False,
	"native_edges":[{"edge_id":25},{"edge_id":26}]}
RAYS={25:[[0,5,1,5]],26:[[0,5,1,5]]}

class CoincidentRayDistanceWitnessTests(unittest.TestCase):
	def test_local_witnesses_are_not_ownership(self):
		row=audit_coincident_ray_distance_witness(POLYGONS,[SIDE],RAYS)[0]
		self.assertEqual(row["status"],"finite_distance_samples_recorded_only")
		self.assertTrue(all(w["left_candidate_closer"] and w["right_candidate_closer"]
			for w in row["witnesses"]))
		self.assertFalse(row["ownership_proven"])

	def test_reverse_ray_blocks(self):
		rays={**RAYS,26:[[0,5,-1,5]]}
		self.assertEqual(audit_coincident_ray_distance_witness(POLYGONS,[SIDE],rays)[0]["status"],
			"blocked_distance_witness")

	def test_missing_ray_blocks(self):
		self.assertEqual(audit_coincident_ray_distance_witness(POLYGONS,[SIDE],{25:RAYS[25]})[0]["status"],
			"blocked_distance_witness")

	def test_incorrect_side_blocks(self):
		bad={**SIDE,"left_face":0,"right_face":1}
		self.assertEqual(audit_coincident_ray_distance_witness(POLYGONS,[bad],RAYS)[0]["status"],
			"blocked_distance_witness")

	def test_ownership_claim_blocks(self):
		self.assertEqual(audit_coincident_ray_distance_witness(POLYGONS,
			[{**SIDE,"ownership_proven":True}],RAYS)[0]["status"],
			"blocked_distance_witness")

if __name__=="__main__":
	unittest.main()
