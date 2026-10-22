"""Native CGAL input-site provenance: no point cells and no guessed owners."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from shapely.geometry import box, LineString

from scripts.cgal_site_ownership import (
	read_sites,attribute_faces,require_sound_attribution)
from scripts.build_cgal_pre_sis import _group_before_sis


class SiteOwnershipTests(unittest.TestCase):
	def test_native_segment_sites_link_to_original_edge_id(self):
		with TemporaryDirectory() as root:
			file=Path(root)/"sites.txt"
			# Original supporting site 0..10m, a CGAL sub-site 1..9m.
			file.write_text("S 0 5000 10000 5000 1000 5000 9000 5000\n"
				"S 10000 5000 20000 5000 11000 5000 19000 5000\n"
				"P 10000 5000\n"
				"S -2000 -2000 -2000 22000 -2000 -2000 -2000 22000\n",
				encoding="utf-8")
			owners={
				((0,5000),(10000,5000)):"a",
				((10000,5000),(20000,5000)):"b"}
			sites,counts=read_sites(file,owners,(0,0))
			self.assertEqual(counts["native_segment_sites"],2)
			self.assertEqual(counts["native_point_sites_omitted"],1)
			self.assertEqual(counts["outer_frame_segment_sites_omitted"],1)
			labels,stats=attribute_faces(
				[box(0,0,10,10),box(10,0,20,10),box(20,0,30,10)],
				sites,counts)
			require_sound_attribution(stats)
			self.assertEqual(labels,["a","b",None])
			self.assertEqual(stats["polygons_without_segment_edge_id"],1)

	def test_site_attribution_rejects_mismatched_polygon_split(self):
		with TemporaryDirectory() as root:
			file=Path(root)/"sites.txt"
			file.write_text(
				"S 0 5000 10000 5000 0 5000 10000 5000\n",
				encoding="utf-8")
			owners={((0,5000),(10000,5000)):"a"}
			sites,counts=read_sites(file,owners,(0,0))
			labels,stats=attribute_faces(
				[box(0,0,5,10),box(5,0,10,10)],sites,counts)
			self.assertEqual(labels,[None,None])
			self.assertEqual(stats["segment_sites_without_unique_face"],1)
			with self.assertRaisesRegex(ValueError,"nicht eindeutig"):
				require_sound_attribution(stats)

	def test_opposite_sites_same_original_edge_merge_before_sis(self):
		geoms=[box(0,0,2,2),box(2,0,4,2),box(10,0,12,2)]
		parts=list(_group_before_sis(geoms,["a","a","a"]))
		self.assertEqual(len(parts),2)
		self.assertEqual(sorted(p.area for _,p in parts),[4,8])

	def test_sites_completely_outside_window_are_not_false_failures(self):
		site=(
			51,"outside",
			LineString(
				[(30,5),(40,5)]))
		labels,stats=attribute_faces([box(0,0,10,10)],[site],
			{"native_segment_sites":1,
				"native_point_sites_omitted":0,
				"outer_frame_segment_sites_omitted":0},
			window=box(0,0,10,10))
		require_sound_attribution(stats)
		self.assertEqual(labels,[None])
		self.assertEqual(stats["segment_sites_outside_window"],1)

	def test_distinct_edge_ids_are_not_merged(self):
		parts=list(_group_before_sis(
			[box(0,0,2,2),box(2,0,4,2)],["a","b"]))
		self.assertEqual({edge_id for edge_id,_ in parts},{"a","b"})
		self.assertEqual(len(parts),2)

	def test_rejects_off_grid_supporting_site(self):
		with TemporaryDirectory() as root:
			file=Path(root)/"sites.txt"
			file.write_text(
				"S 0.1 5000 10000 5000 0 5000 10000 5000\n")
			with self.assertRaisesRegex(ValueError,"integer millimetre"):
				read_sites(file,{((0,5000),(10000,5000)):"a"},(0,0))


if __name__=="__main__":
	unittest.main()
