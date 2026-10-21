import unittest
from scripts.cgal_coincident_endpoint_group import audit_coincident_endpoint_group

P=("P",(0.,0.))
UP=("S",(0.,0.,0.,1000.))
DOWN=("S",(0.,-1000.,0.,0.))
OTHER=("P",(10.,10.))
I={"primary_finite":False,"neighbor_finite":True,
	"opposite_sites":"OPP INF | NEIGH S 0 0 1000 0"}
R={1:[[0.,0.,1.,0.]],2:[[0.,0.,1.,0.]]}

class CoincidentEndpointGroupTests(unittest.TestCase):
	def run_group(self,edges=None,rays=None,incidence=None):
		return audit_coincident_endpoint_group([1,2],
			edges if edges is not None else [(1,(P,UP),[]),(2,(P,DOWN),[])],
			rays if rays is not None else R,
			incidence if incidence is not None else {1:I,2:I})

	def test_valid_group_is_never_proof(self):
		result=self.run_group()
		self.assertEqual(result["status"],"grouped_diagnostic_only")
		self.assertEqual(result["left_segment"]["coordinates"],list(UP[1]))
		self.assertEqual(result["right_segment"]["coordinates"],list(DOWN[1]))
		self.assertFalse(result["ownership_proven"])

	def test_distinct_points_rejected(self):
		result=self.run_group(edges=[(1,(P,UP),[]),(2,(OTHER,DOWN),[])])
		self.assertEqual(result["status"],"rejected")

	def test_regular_point_segment_cell_not_grouped(self):
		result=self.run_group(edges=[(1,(P,UP),[]),(2,(P,UP),[])])
		self.assertEqual(result["status"],"rejected")

	def test_opposite_ray_directions_rejected(self):
		result=self.run_group(rays={1:R[1],2:[[0.,0.,-1.,0.]]})
		self.assertEqual(result["status"],"rejected")

	def test_opposite_primal_site_mismatch_rejected(self):
		info={**I,"opposite_sites":"different"}
		result=self.run_group(incidence={1:I,2:info})
		self.assertEqual(result["status"],"rejected")

	def test_single_dual_not_grouped(self):
		result=audit_coincident_endpoint_group([1],[],{}, {})
		self.assertEqual(result["status"],"rejected")

if __name__=="__main__":
	unittest.main()
