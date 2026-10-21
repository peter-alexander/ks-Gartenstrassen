"""Original LINEAR_USE line-to-polygon matching, including ambiguity exports."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from shapely.geometry import LineString, box

from scripts.cgal_original_line_assignment import (
	assign_by_intersections, diagnostic_paths, write_diagnostics)


class SourceIntersectionTests(unittest.TestCase):
	def test_one_multiple_none_and_conflicting_edge_ids(self):
		polygons=[box(0,0,10,10),box(10,0,20,10)]
		records=[
			("lu-1","A",LineString([(2,5),(8,5)])),
			("lu-2","B",LineString([(12,5),(18,5)])),
			("lu-3","C",LineString([(2,1),(18,1)])),
			("lu-4","D",LineString([(30,5),(40,5)])),
			("lu-5","E",LineString([(2,6),(8,6)])),
		]
		r=assign_by_intersections(polygons,records)
		self.assertEqual(r["labels"],[None,"B"])
		self.assertEqual([x["object_id"] for x in r["multiple"]],["lu-3"])
		self.assertEqual([x["object_id"] for x in r["missing"]],["lu-4"])
		self.assertEqual(r["multiple"][0]["positive_length_hits"],2)
		self.assertEqual(r["conflicts"][0]["edge_ids"],["A","E"])
		self.assertEqual(r["unassigned"][0]["reason"],"conflicting_edge_ids")
		self.assertEqual(r["report"]["polygons_unambiguously_assigned"],1)
		with TemporaryDirectory() as temp:
			target=Path(temp)/"result.geojson"
			paths=write_diagnostics(target,polygons,records,r,
				lambda x,y:(x,y))
			self.assertEqual(set(paths),
				{"multiple","missing","conflicts","unassigned","report"})
			for kind in ("multiple","missing","conflicts","unassigned"):
				data=json.loads(paths[kind].read_text(encoding="utf-8"))
				self.assertEqual(len(data["features"]),1)
			self.assertEqual(json.loads(paths["report"].read_text(
				encoding="utf-8"))["lines_multiple_polygons"],1)
			with self.assertRaises(FileExistsError):
				write_diagnostics(target,polygons,records,r,
					lambda x,y:(x,y))

	def test_multiple_source_lines_same_edge_id_are_not_conflict(self):
		shape=[box(0,0,10,10)]
		records=[
			("lu-a","A",LineString([(1,1),(4,1)])),
			("lu-b","A",LineString([(6,6),(9,6)]))]
		r=assign_by_intersections(shape,records)
		self.assertEqual(r["labels"],["A"])
		self.assertEqual(r["conflicts"],[])
		self.assertEqual(r["multiple"],[])

	def test_boundary_only_touch_is_reported_as_multiple(self):
		# Shapely intersects() counts the endpoint touching the next cell.
		polygons=[box(0,0,10,10),box(10,0,20,10)]
		records=[("touch","A",LineString([(2,5),(10,5)]))]
		r=assign_by_intersections(polygons,records)
		self.assertEqual(len(r["multiple"]),1)
		self.assertEqual(r["multiple"][0]["positive_length_hits"],1)
		self.assertEqual(r["multiple"][0]["boundary_only_hits"],1)
		self.assertEqual(r["report"]["multiple_from_boundary_contacts_only"],1)
		self.assertEqual(r["labels"],[None,None])
		self.assertEqual(len(r["unassigned"]),2)

	def test_line_overlapping_shared_boundary_is_also_ambiguous(self):
		polygons=[box(0,0,10,10),box(10,0,20,10)]
		r=assign_by_intersections(polygons,[
			("shared","A",LineString([(10,2),(10,8)]))])
		self.assertEqual(len(r["multiple"]),1)
		self.assertEqual(r["multiple"][0]["positive_length_hits"],2)

	def test_unmatched_polygon_is_explicitly_diagnosed(self):
		polygons=[box(0,0,10,10),box(20,0,30,10)]
		r=assign_by_intersections(polygons,[
			("a","A",LineString([(2,2),(8,2)]))])
		self.assertEqual(r["labels"],["A",None])
		self.assertEqual(r["unassigned"][0]["polygon_index"],1)
		self.assertEqual(r["unassigned"][0]["intersecting_lines"],0)


if __name__=="__main__":
	unittest.main()
