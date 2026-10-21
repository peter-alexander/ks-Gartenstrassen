"""No-geometry streaming summary of the large saved CGAL diagnostics."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.summarize_cgal_intersections import summarize


class SavedCGALSummaryTests(unittest.TestCase):
	def test_streams_saved_layers_without_loading_geometry(self):
		with TemporaryDirectory() as root:
			base=Path(root)/"cgal_original_line_intersections_sis_wien"
			report={
				"schema":"original-line-polygon-intersections-v1",
				"line_count":4,"polygon_count":10,
				"lines_exactly_one_polygon":1,
				"lines_multiple_polygons":3,"lines_no_polygon":0,
				"polygons_conflicting_edge_ids":1,
				"polygons_without_unambiguous_edge_id":3}
			(base.with_name(base.name+"__zuordnungsbericht.json")).write_text(
				json.dumps(report),encoding="utf-8")
			multiple=base.with_name(base.name+"__linien_mehrere_flaechen.geojson")
			multiple.write_text('{"type":"FeatureCollection","features":[\n'
				+'{"properties":{"object_id":"a","positive_length_hits":1,"boundary_only_hits":1},"geometry":null},\n'
				+'{"properties":{"object_id":"b","positive_length_hits":2,"boundary_only_hits":0},"geometry":null},\n'
				+'{"properties":{"object_id":"c","positive_length_hits":0,"boundary_only_hits":3},"geometry":null}\n'
				+']}\n',encoding="utf-8")
			unassigned=base.with_name(base.name+"__flaechen_ohne_eindeutige_edge_id.geojson")
			unassigned.write_text('{"type":"FeatureCollection","features":[\n'
				+'{"properties":{"polygon_index":0,"reason":"no_unique_source_line","intersecting_lines":0},"geometry":null},\n'
				+'{"properties":{"polygon_index":1,"reason":"no_unique_source_line","intersecting_lines":3},"geometry":null},\n'
				+'{"properties":{"polygon_index":2,"reason":"conflicting_edge_ids","intersecting_lines":2},"geometry":null}\n'
				+']}\n',encoding="utf-8")
			stats=summarize(base)
			self.assertEqual(stats["multiple_positive_length_hits"],
				{"0":1,"1":1,"2+":1})
			self.assertEqual(stats["multiple_boundary_only_hits"],
				{"0":1,"1":1,"2+":1})
			self.assertEqual(stats["unassigned_polygons_by_intersecting_source_lines"],
				{"0":1,"2+":2})
			self.assertEqual(stats["unassigned_polygons_by_reason"],
				{"no_unique_source_line":2,"conflicting_edge_ids":1})
			self.assertEqual(stats["examples_multiple_positive_length"][0]["object_id"],"b")

	def test_rejects_mismatched_feature_counts(self):
		with TemporaryDirectory() as root:
			base=Path(root)/"diag"
			(base.with_name("diag__zuordnungsbericht.json")).write_text(
				json.dumps({"schema":"original-line-polygon-intersections-v1",
					"lines_multiple_polygons":1}))
			(base.with_name("diag__linien_mehrere_flaechen.geojson")).write_text(
				'{"type":"FeatureCollection","features":[]}\n')
			with self.assertRaisesRegex(ValueError,"Mehrfachtreffer"):
				summarize(base)


if __name__=="__main__":
	unittest.main()
