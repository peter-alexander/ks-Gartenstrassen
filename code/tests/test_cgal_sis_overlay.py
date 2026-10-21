"""CGAL SIS overlay: tiled and untiled mask must yield identical area."""
import unittest

from shapely.geometry import box
from shapely import union_all

from scripts.build_cgal_voronoi_geojson import _assign


class CGALSISOverlayTests(unittest.TestCase):
	def test_preclipped_tile_parts_match_merged_mask(self):
		mask_parts=[box(0,0,10,8),box(10,0,20,8)]
		mask=union_all(mask_parts)
		polygons=[box(0,0,5,10),box(5,0,15,10),box(15,0,20,10)]
		# Three sites, one in each Voronoi region, metre -> mm integers.
		owners={
			((1000,4000),(2000,4000)):"west",
			((9000,4000),(11000,4000)):"middle",
			((18000,4000),(19000,4000)):"east"}
		old,baseline=_assign(polygons,mask,owners,(0,0),batch_size=2)
		new,optimized=_assign(polygons,mask,owners,(0,0),
			mask_parts=mask_parts,batch_size=2)
		self.assertEqual(set(old),set(new))
		self.assertAlmostEqual(sum(g.area for g in old.values()),160)
		self.assertAlmostEqual(sum(g.area for g in new.values()),160)
		for edge_id in old:
			self.assertLess(old[edge_id].symmetric_difference(
				new[edge_id]).area,1e-8)
		self.assertAlmostEqual(baseline["gap_m2"],optimized["gap_m2"])
		self.assertAlmostEqual(baseline["overlap_m2"],optimized["overlap_m2"])
		self.assertEqual(optimized["mask_tile_parts"],2)

	def test_complete_voronoi_face_keeps_one_owner_across_sis_pieces(self):
		polygons=[box(0,0,100,10)]
		parts=[box(0,0,10,10),box(90,0,100,10)]
		mask=union_all(parts)
		owners={
			((1000,4000),(2000,4000)):"west",
			((98000,4000),(99000,4000)):"east"}
		grouped,report=_assign(polygons,mask,owners,(0,0),
			mask_parts=parts,face_labels=["west"],batch_size=1)
		self.assertEqual(set(grouped),{"west"})
		self.assertAlmostEqual(grouped["west"].area,200)
		self.assertAlmostEqual(report["gap_m2"],0)

	def test_explicit_cgal_face_owner_overrides_nearest_heuristic(self):
		# The generator identity is authoritative even if a sample at
		# the SIS piece would otherwise select a different axis.
		polygons=[box(0,0,10,10),box(10,0,20,10)]
		mask=box(0,0,20,10)
		owners={
			((1000,4000),(2000,4000)):"west",
			((18000,4000),(19000,4000)):"east"}
		result,stats=_assign(polygons,mask,owners,(0,0),
			mask_parts=[mask],face_labels=["east","west"],batch_size=1)
		self.assertAlmostEqual(result["east"].area,100)
		self.assertAlmostEqual(result["west"].area,100)
		self.assertAlmostEqual(stats["assigned_m2"],200)

	def test_default_owner_is_assigned_before_sis_clipping(self):
		polygons=[box(0,0,10,10)]
		mask=box(0,0,10,10)
		owners={((1000,4000),(2000,4000)):"west"}
		result,stats=_assign(polygons,mask,owners,(0,0))
		self.assertEqual(set(result),{"west"})
		self.assertAlmostEqual(stats["assigned_m2"],100)

	def test_reject_invalid_batch_size(self):
		with self.assertRaises(ValueError):
			_assign([],box(0,0,1,1),{},(0,0),batch_size=0)


if __name__=="__main__":
	unittest.main()
