"""Regression checks for CGAL dual geometry before running full Vienna."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from shapely.geometry import LineString, Polygon, box

from scripts.build_cgal_voronoi_geojson import (
	_polygon_candidates, _record_line, _export_wgs84_polygon, build)


class CGALFullViennaTests(unittest.TestCase):
	def test_zero_length_draw_fragment_is_not_a_boundary(self):
		self.assertIsNone(_record_line("S",((1.,1.),(1.,1.)),
			box(0,0,10,10)))

	def test_segment_is_clipped_to_city_boundary(self):
		result=_record_line("S",((-10.,5.),(20.,5.)),
			box(0,0,10,10))
		self.assertEqual(result.bounds,(0.,5.,10.,5.))

	def test_polygonization_partitions_complete_rectangle(self):
		window=box(0,0,10,10)
		polygons,stats=_polygon_candidates(
			[LineString([(5,0),(5,10)])],window)
		self.assertEqual(len(polygons),2)
		self.assertAlmostEqual(sum(p.area for p in polygons),100.)
		self.assertLess(stats["gap_m2"],1e-6)

	def test_geojson_export_keeps_valid_polygon(self):
		geom=box(0,0,10,10)
		out,repair=_export_wgs84_polygon(geom,lambda x,y:(x,y),
			lambda x,y:(x,y),edge_id="a")
		self.assertTrue(out.equals(geom))
		self.assertIsNone(repair)

	def test_geojson_export_rejects_ambiguous_self_intersection(self):
		geom=Polygon([(0,0),(10,10),(0,10),(10,0),(0,0)])
		with self.assertRaisesRegex(ValueError,"ungültig"):
			_export_wgs84_polygon(geom,lambda x,y:(x,y),
				lambda x,y:(x,y),edge_id="a")

	def test_diagnostic_does_not_overwrite_existing_report(self):
		with TemporaryDirectory() as temp:
			directory=Path(temp)
			report=directory/"report.json"
			report.write_text("old",encoding="utf-8")
			with self.assertRaises(FileExistsError):
				build(None,None,None,None,directory/"nonexistent",
					directory/"existing.geojson",
					diagnostic_report=report)
			self.assertEqual(report.read_text(encoding="utf-8"),"old")

	def test_diagnostic_mode_allows_existing_geojson(self):
		with TemporaryDirectory() as temp:
			directory=Path(temp)
			geojson=directory/"existing.geojson"
			geojson.write_text("old",encoding="utf-8")
			with self.assertRaises(FileNotFoundError):
				build(None,None,None,None,directory/"nonexistent",
					geojson,diagnostic_report=directory/"report.json")
			self.assertEqual(geojson.read_text(encoding="utf-8"),"old")

	def test_invalid_ray_direction_raises(self):
		with self.assertRaisesRegex(ValueError,"Vektor"):
			_record_line("R",((5.,5.),(5.,5.)),box(0,0,10,10))


if __name__=="__main__":
	unittest.main()
