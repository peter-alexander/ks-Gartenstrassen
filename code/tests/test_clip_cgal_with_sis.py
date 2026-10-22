"""Final SIS overlap: only SIS-covered CGAL area, original edge_id intact."""
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pyproj import Transformer
from shapely.geometry import MultiPolygon,Polygon,box,mapping,shape
from shapely.ops import transform
from shapely.validation import explain_validity
from shapely.wkb import dumps

from scripts.clip_cgal_with_sis import (
	clip,_export_valid_wgs84,_clip_feature,_strip_projection_collapsed_holes)


TO_WGS=Transformer.from_crs(31256,4326,always_xy=True).transform
TO_METRIC=Transformer.from_crs(4326,31256,always_xy=True).transform


def _input_feature(edge_id,metric,**more):
	return {"type":"Feature","properties":{
		"edge_id":edge_id,"area_m2":metric.area,
		"sis_clipped":False,"preview_based":True,
		"recovered_by_debug_area_filter":False,**more},
		"geometry":mapping(transform(TO_WGS,metric))}


def _dissolved(path,features):
	with path.open("w",encoding="utf-8") as out:
		out.write('{"type":"FeatureCollection","features":[\n')
		for index,feature in enumerate(features):
			if index:
				out.write(",\n")
			json.dump(feature,out,separators=(",",":"))
		out.write('\n],"metadata":{"schema":'
			'"cgal-original-edge-id-turn-use-hull-dissolve-v6-final-debug-area-filter",'
			'"dissolved_by":"edge_id","sis_clipped":false}}\n')


def _sis_database(path,polygons,*,schema="sis-wien-index-v5",with_digest=True):
	with sqlite3.connect(path) as db:
		db.executescript("""
			CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
			CREATE TABLE features(
				id INTEGER PRIMARY KEY,source_id TEXT NOT NULL,
				belag TEXT NOT NULL,geom BLOB NOT NULL);
			CREATE VIRTUAL TABLE feature_index USING rtree(
				id,minx,maxx,miny,maxy);
		""")
		for k,v in (("schema",schema),("provider","SISBELAGOGD"),
				("crs","EPSG:31256"),("sha256","synthetic-test-sha" if with_digest else "")):
			db.execute("INSERT INTO metadata VALUES(?,?)",(k,v))
		for i,geom in enumerate(polygons,1):
			db.execute("INSERT INTO features VALUES(?,?,?,?)",(
				i,f"SIS-{i}","BL" if i%2 else "AS",dumps(geom)))
			x0,y0,x1,y1=geom.bounds
			db.execute("INSERT INTO feature_index VALUES(?,?,?,?,?)",
				(i,x0,x1,y0,y1))


class WGS84ProjectionRegressionTests(unittest.TestCase):
	def _near_touching_valid_metric_polygon(self):
		# An intact metric polygon with a hole only 1 nanometre from
		# its outer shell. In EPSG:31256 it is valid, but during
		# conversion to WGS84 the gap can collapse and self-intersect.
		x,y=TO_METRIC(16.34,48.21)
		return Polygon([
			(x,y),(x+100,y),(x+100,y+20),(x,y+20)],
			holes=[[
				(x+1e-9,y+5),(x+4,y+5),
				(x+4,y+10),(x+1e-9,y+10)]])

	def _collapsed_seven_metre_hole(self):
		# Reproduce the observed SIS failure mode: "Too few points
		# in geometry component" with ~7-8 metres Hausdorff difference,
		# but a genuine source hole of less than a billionth of m².
		x,y=TO_METRIC(16.4848255346621,48.2407774556703)
		gap=1e-10
		return Polygon([
			(x,y),(x+20,y),(x+20,y+20),(x,y+20)],
			holes=[[
				(x+10,y+5),(x+10+gap,y+5),
				(x+10+gap,y+12),(x+10,y+12)]])

	def test_collapsed_seven_metre_wgs84_hole_keeps_all_real_area(self):
		metric=self._collapsed_seven_metre_hole()
		self.assertTrue(metric.is_valid)
		raw=transform(TO_WGS,metric)
		self.assertTrue(explain_validity(raw).startswith(
			"Too few points in geometry component"))
		self.assertLess(Polygon(metric.interiors[0]).area,1e-8)
		repaired,event=_export_valid_wgs84(
			metric,TO_METRIC,TO_WGS,"collapsed-7m")
		self.assertTrue(repaired.is_valid)
		self.assertEqual(event["repair"],
			"remove_only_projection_collapsed_interior_rings")
		self.assertEqual(event["discarded_collapsed_holes"],1)
		self.assertGreater(event["boundary_shift_m"],6)
		self.assertLess(event["discarded_metric_hole_area_m2"],1e-8)
		converted=transform(TO_METRIC,repaired)
		self.assertLess(abs(converted.area-metric.area),0.01)

	def test_collapsed_hole_does_not_remove_other_valid_interior_rings(self):
		metric=self._collapsed_seven_metre_hole()
		x0,y0,x1,y1=metric.bounds
		normally_sized=[(x0+3,y0+5),(x0+6,y0+5),
			(x0+6,y0+8),(x0+3,y0+8)]
		metric=Polygon(metric.exterior,[
			list(metric.interiors[0].coords),normally_sized])
		self.assertTrue(metric.is_valid)
		wgs,event=_export_valid_wgs84(
			metric,TO_METRIC,TO_WGS,"keep-ordinary-hole")
		self.assertTrue(wgs.is_valid)
		self.assertEqual(event["discarded_collapsed_holes"],1)
		self.assertEqual(len(wgs.interiors),1)
		metric_roundtrip=transform(TO_METRIC,wgs)
		self.assertAlmostEqual(metric_roundtrip.area,metric.area,places=2)

	def test_reject_large_hole_masquerading_as_collapsed(self):
		x,y=TO_METRIC(16.4848255346621,48.2407774556703)
		metric=Polygon([(x,y),(x+20,y),(x+20,y+20),(x,y+20)],
			holes=[[(x+5,y+5),(x+9,y+5),
				(x+9,y+12),(x+5,y+12)]])
		exterior=transform(TO_WGS,metric).exterior
		lon,lat=exterior.coords[0]
		# Synthetic corrupt WGS84 ring with only two unique points:
		# Do not allow it to replace a legitimate 28m² source hole.
		corrupt=Polygon(exterior,holes=[[
			(lon+1e-5,lat+1e-5),
			(lon+1e-5,lat+1e-5),
			(lon+2e-5,lat+2e-5),
			(lon+2e-5,lat+2e-5)]])
		self.assertIsNone(_strip_projection_collapsed_holes(
			metric,corrupt,TO_METRIC))

	def test_sis_feature_records_collapsed_hole_method(self):
		metric=self._collapsed_seven_metre_hole()
		x0,y0,x1,y1=metric.bounds
		source=_input_feature("collapsed-hole-edge",
			box(x0-2,y0-2,x1+2,y1+2))
		with patch("scripts.clip_cgal_with_sis.sis_mask",
				return_value=metric):
			from collections import Counter
			stats=Counter()
			result=_clip_feature(source,None,TO_METRIC,TO_WGS,stats)
		self.assertEqual(result["properties"]["edge_id"],"collapsed-hole-edge")
		self.assertTrue(result["properties"]["wgs84_projection_repaired"])
		self.assertEqual(result["properties"]["wgs84_repair_method"],
			"remove_only_projection_collapsed_interior_rings")
		self.assertTrue(shape(result["geometry"]).is_valid)
		self.assertEqual(stats["wgs84_collapsed_holes_removed"],1)


	def test_valid_metric_sis_can_become_invalid_in_wgs84(self):
		metric=self._near_touching_valid_metric_polygon()
		self.assertTrue(metric.is_valid)
		raw=transform(TO_WGS,metric)
		self.assertFalse(raw.is_valid,explain_validity(raw))
		self.assertIn("Self-intersection",explain_validity(raw))
		repaired,event=_export_valid_wgs84(
			metric,TO_METRIC,TO_WGS,"test-edge")
		self.assertIsNotNone(event)
		self.assertTrue(repaired.is_valid)
		self.assertIn(repaired.geom_type,("Polygon","MultiPolygon"))
		self.assertEqual(event["edge_id"],"test-edge")
		self.assertLessEqual(event["area_shift_m2"],
			event["area_tolerance_m2"])
		self.assertLessEqual(event["boundary_shift_m"],0.02)
		repaired_metric=transform(TO_METRIC,repaired)
		self.assertLess(abs(repaired_metric.area-metric.area),0.01)

	def test_healthy_wgs84_sis_polygon_is_never_repaired(self):
		x,y=TO_METRIC(16.34,48.21)
		metric=box(x,y,x+30,y+20)
		self.assertTrue(metric.is_valid)
		with patch("scripts.clip_cgal_with_sis.make_valid",
				side_effect=AssertionError("make_valid must not run")):
			geom,event=_export_valid_wgs84(
				metric,TO_METRIC,TO_WGS,"healthy")
		self.assertIsNone(event)
		self.assertTrue(geom.is_valid)

	def test_reject_non_equivalent_repair_instead_of_silently_changing_area(self):
		metric=self._near_touching_valid_metric_polygon()
		with patch("scripts.clip_cgal_with_sis.make_valid",
				return_value=box(16.3,48.2,16.35,48.25)):
			with self.assertRaisesRegex(ValueError,
					"kontrollierte Reparatur abgelehnt"):
				_export_valid_wgs84(metric,TO_METRIC,TO_WGS,"must-not-lose-area")

	def test_sis_feature_records_conservative_projection_repair(self):
		metric=self._near_touching_valid_metric_polygon()
		x,y=metric.bounds[:2]
		source=_input_feature("problem-edge",
			box(x-1,y-1,x+101,y+21))
		with patch("scripts.clip_cgal_with_sis.sis_mask",
				return_value=metric):
			from collections import Counter
			stats=Counter()
			result=_clip_feature(source,None,TO_METRIC,TO_WGS,stats)
		self.assertTrue(result["properties"]["sis_clipped"])
		self.assertTrue(result["properties"]["wgs84_projection_repaired"])
		self.assertEqual(result["properties"]["edge_id"],"problem-edge")
		self.assertTrue(shape(result["geometry"]).is_valid)
		self.assertEqual(stats["wgs84_repaired_features"],1)


class FinalSISIntersectionTests(unittest.TestCase):
	def test_actual_wien_index_rtree_clips_to_all_sis_classes_and_keeps_edge_id(self):
		with TemporaryDirectory() as temp:
			root=Path(temp)
			x,y=1500,340000
			a=box(x,y,x+20,y+10)
			b=box(x+50,y,x+60,y+10)
			mask1=box(x+2,y+2,x+8,y+8)
			mask2=box(x+12,y+2,x+18,y+8)
			source=root/"before_sis.geojson"
			_dissolved(source,[
				_input_feature("first",a,
					recovered_by_debug_area_filter=True),
				_input_feature("second",b)])
			db=root/"sis-wien.sqlite"
			_sis_database(db,[mask1,mask2])
			out=root/"after_sis.geojson"
			stats=clip(source,db,out)
			document=json.loads(out.read_text())
			self.assertEqual(len(document["features"]),1)
			feature=document["features"][0]
			self.assertEqual(feature["properties"]["edge_id"],"first")
			self.assertEqual(feature["properties"]["area_m2"],72)
			self.assertAlmostEqual(feature["properties"]["pre_sis_area_m2"],200,places=3)
			self.assertTrue(feature["properties"]["sis_clipped"])
			self.assertTrue(feature["properties"]["recovered_by_debug_area_filter"])
			self.assertEqual(feature["properties"]["sis_mask"],"all_belags_all_types")
			self.assertEqual(feature["geometry"]["type"],"MultiPolygon")
			result=transform(TO_METRIC,shape(feature["geometry"]))
			self.assertLess(result.symmetric_difference(mask1.union(mask2)).area,.05)
			self.assertEqual(stats["pre_sis_features"],2)
			self.assertEqual(stats["features_with_sis_overlap"],1)
			self.assertEqual(stats["without_sis_overlap"],1)
			self.assertEqual(stats["sis_multipolygon_features"],1)
			self.assertEqual(document["metadata"]["sis_sha256"],"synthetic-test-sha")
			with self.assertRaises(FileExistsError):
				clip(source,db,out)

	def test_polygon_with_multiple_sis_features_does_not_double_count_overlap(self):
		with TemporaryDirectory() as temp:
			root=Path(temp)
			x,y=1500,340000
			footprint=box(x,y,x+20,y+20)
			sis_a=box(x+1,y+1,x+12,y+12)
			sis_b=box(x+9,y+9,x+18,y+18)
			pre=root/"before.geojson"
			_dissolved(pre,[_input_feature("overlap",footprint)])
			db=root/"sis.sqlite"
			_sis_database(db,[sis_a,sis_b])
			out=root/"after.geojson"
			stats=clip(pre,db,out)
			self.assertEqual(len(json.loads(out.read_text())["features"]),1)
			expected=sis_a.union(sis_b)
			self.assertAlmostEqual(stats["sis_overlap_area_sum_m2"],expected.area,places=5)
			self.assertEqual(json.loads(out.read_text())["features"][0]["properties"]["edge_id"],"overlap")

	def test_only_boundary_touch_is_not_a_polygonal_sis_hit(self):
		with TemporaryDirectory() as temp:
			root=Path(temp)
			x,y=1500,340000
			pre=root/"before.geojson"
			_dissolved(pre,[_input_feature("border",box(x,y,x+5,y+5))])
			db=root/"sis.sqlite"
			_sis_database(db,[box(x+5,y,x+10,y+5)])
			out=root/"out.geojson"
			stats=clip(pre,db,out)
			self.assertEqual(json.loads(out.read_text())["features"],[])
			self.assertEqual(stats["without_sis_overlap"],1)

	def test_invalid_index_fails_without_modifying_existing_output(self):
		with TemporaryDirectory() as temp:
			root=Path(temp)
			pre=root/"before.geojson"
			_dissolved(pre,[_input_feature("x",box(1500,340000,1510,340010))])
			db=root/"sis.sqlite"
			_sis_database(db,[box(1500,340000,1505,340005)],
				schema="wrong-sis-v0")
			out=root/"out.geojson"
			out.write_text("PREVIOUS_VALID_OUTPUT",encoding="utf-8")
			with self.assertRaisesRegex(ValueError,"SIS-Wien-Index"):
				clip(pre,db,out,replace_existing=True)
			self.assertEqual(out.read_text(),"PREVIOUS_VALID_OUTPUT")

	def test_missing_sis_index_never_produces_unclipped_output(self):
		with TemporaryDirectory() as temp:
			root=Path(temp)
			pre=root/"before.geojson"
			_dissolved(pre,[_input_feature("x",box(1500,340000,1510,340010))])
			with self.assertRaises(FileNotFoundError):
				clip(pre,root/"nonexistent.sqlite",root/"after.geojson")
			self.assertFalse((root/"after.geojson").exists())

	def test_invalid_later_feature_rolls_back_entire_output(self):
		with TemporaryDirectory() as temp:
			root=Path(temp)
			x,y=1500,340000
			pre=root/"before.geojson"
			_dissolved(pre,[
				_input_feature("good",box(x,y,x+10,y+10)),
				_input_feature("bad",box(x+20,y,x+30,y+10),sis_clipped=True)])
			db=root/"sis.sqlite"
			_sis_database(db,[box(x,y,x+40,y+20)])
			out=root/"after.geojson"
			out.write_text("OLD",encoding="utf-8")
			with self.assertRaisesRegex(ValueError,"bereits"):
				clip(pre,db,out,replace_existing=True)
			self.assertEqual(out.read_text(),"OLD")

	def test_rejects_malformed_or_old_pre_sis_metadata(self):
		with TemporaryDirectory() as temp:
			root=Path(temp)
			x,y=1500,340000
			db=root/"sis.sqlite"
			_sis_database(db,[box(x,y,x+5,y+5)])
			pre=root/"before.geojson"
			_dissolved(pre,[_input_feature("one",box(x,y,x+10,y+10))])
			s=pre.read_text().replace('"dissolved_by":"edge_id"', '"dissolved_by":"unknown"')
			pre.write_text(s)
			with self.assertRaisesRegex(ValueError,"CGAL-Dissolve"):
				clip(pre,db,root/"after.geojson")
			self.assertFalse((root/"after.geojson").exists())


if __name__=="__main__":
	unittest.main()
