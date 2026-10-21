"""Regression checks for CGAL dual geometry before running full Vienna."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from shapely.geometry import LineString, Polygon, MultiPolygon, box
from shapely.ops import transform
from pyproj import Transformer
import numpy as np

from scripts.build_cgal_voronoi_geojson import (
	_polygon_candidates, _record_line, _export_wgs84_polygon, _connected_components)


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

	def test_projection_degenerate_tiny_hole_is_repaired_in_metric_crs(self):
		# This mimics the Vienna failure: a sub-nanometre hole becomes
		# unrepresentable in WGS84, while the EPSG:31256 roundtrip alone
		# introduces >0.01 m² of symmetric difference in a 50 m square.
		x,y=10000.,340000.
		outer=box(x,y,x+50,y+50)
		tiny_hole=box(x+25,y+25,x+25+1e-10,y+25+1e-10)
		metric=Polygon(outer.exterior.coords,[tiny_hole.exterior.coords])
		to_wgs=Transformer.from_crs(31256,4326,always_xy=True).transform
		to_metric=Transformer.from_crs(4326,31256,always_xy=True).transform
		self.assertTrue(metric.is_valid)
		self.assertFalse(transform(to_wgs,metric).is_valid)
		result,repair=_export_wgs84_polygon(
			metric,to_wgs,to_metric,edge_id="example")
		self.assertTrue(result.is_valid)
		self.assertEqual(repair["method"],
			"metric_precision_cleanup_before_wgs84")
		self.assertLess(repair["symmetric_difference_m2"],0.01)
		# Deliberately not used as a repair criterion: includes projection drift.
		self.assertGreater(metric.symmetric_difference(
			transform(to_metric,result)).area,0.01)

	def test_projection_repair_does_not_discard_material_hole(self):
		outer=box(0,0,10,10)
		hole=box(5.1,5.1,5.3,5.3)
		metric=Polygon(outer.exterior.coords,[hole.exterior.coords])
		def coarse_projection(x,y):
			return np.round(x,0),np.round(y,0)
		with self.assertRaisesRegex(ValueError,"ohne flächentreue"):
			_export_wgs84_polygon(metric,coarse_projection,
				lambda x,y:(x,y),edge_id="material-hole")

	def test_disconnected_components_remain_separate(self):
		parts=_connected_components(MultiPolygon([
			box(0,0,2,2),box(5,0,7,2)]))
		self.assertEqual(len(parts),2)
		self.assertAlmostEqual(sum(p.area for p in parts),8)

	def test_polygons_touching_only_at_vertex_are_one_group(self):
		parts=_connected_components(MultiPolygon([
			box(0,0,2,2),box(2,2,4,4)]))
		self.assertEqual(len(parts),1)
		self.assertAlmostEqual(parts[0].area,8)

	def test_transitive_touching_connects_a_chain(self):
		parts=_connected_components(MultiPolygon([
			box(0,0,2,2),box(2,2,4,4),box(4,4,6,6)]))
		self.assertEqual(len(parts),1)
		self.assertAlmostEqual(parts[0].area,12)

	def test_invalid_ray_direction_raises(self):
		with self.assertRaisesRegex(ValueError,"Vektor"):
			_record_line("R",((5.,5.),(5.,5.)),box(0,0,10,10))


if __name__=="__main__":
	unittest.main()
