import unittest
from scripts.cgal_degenerate_ray_sides import audit_degenerate_ray_sides


class DegenerateRaySidesTests(unittest.TestCase):
	def test_opposite_segments_share_endpoint_and_line(self):
		point={"kind":"P","coordinates":[0.,10000.]}
		upper={"kind":"S","coordinates":[0.,10000.,0.,20000.]}
		lower={"kind":"S","coordinates":[0.,0.,0.,10000.]}
		records=[{"edge_id":18,"fragment_kind":"R",
			"clipped_bounds":[-5.,10.,0.,10.],"sites":[point,upper]},
			{"edge_id":22,"fragment_kind":"R",
			"clipped_bounds":[-5.,10.,0.,10.],"sites":[point,lower]}]
		result=audit_degenerate_ray_sides([{"face_indices":[6,7],
			"overlapping_native_sources":records}])
		self.assertEqual(len(result),1)
		self.assertEqual({tuple(s["endpoint_sides"]) for s in
			result[0]["segments"]},{("on_line","left"),("right","on_line")})
		self.assertEqual(result[0]["native_edge_ids"],[18,22])

	def test_incompatible_sources_are_not_classified(self):
		point={"kind":"P","coordinates":[0.,10000.]}
		segment={"kind":"S","coordinates":[0.,0.,0.,10000.]}
		record={"edge_id":1,"fragment_kind":"S",
			"clipped_bounds":[-5.,10.,0.,10.],"sites":[point,segment]}
		self.assertEqual(audit_degenerate_ray_sides([{
			"face_indices":[1,2],
			"overlapping_native_sources":[record,record]}]),[])


if __name__=="__main__":
	unittest.main()
