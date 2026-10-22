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
	clip,_export_valid_wgs84,_clip_feature,_strip_projection_collapsed_holes,
	_recover_collapsed_metric_input,_repair_metric_self_intersection)


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
	def test_invalid_wgs84_ring_is_exported_as_valid_polygon(self):
		x,y=TO_METRIC(16.4848255346621,48.2407774556703)
		metric=Polygon([
			(x,y),(x+20,y),(x+20,y+20),(x,y+20)],
			holes=[[
				(x+10,y+5),(x+10+1e-10,y+5),
				(x+10+1e-10,y+12),(x+10,y+12)]])
		self.assertTrue(metric.is_valid)
		self.assertFalse(transform(TO_WGS,metric).is_valid)
		export,event=_export_valid_wgs84(metric,TO_METRIC,TO_WGS,"edge")
		self.assertTrue(export.is_valid)
		self.assertIn(export.geom_type,("Polygon","MultiPolygon"))
		self.assertEqual(event["repair"],"make_valid_polygonal_export")
		self.assertEqual(event["edge_id"],"edge")

	def test_healthy_wgs84_polygon_unchanged(self):
		x,y=TO_METRIC(16.34,48.21)
		metric=box(x,y,x+30,y+20)
		with patch("scripts.clip_cgal_with_sis.make_valid",
				side_effect=AssertionError("unexpected geometry repair")):
			export,event=_export_valid_wgs84(metric,TO_METRIC,TO_WGS,"good")
		self.assertTrue(export.is_valid)
		self.assertIsNone(event)

	def test_repaired_sis_feature_keeps_edge_id(self):
		x,y=TO_METRIC(16.4848255346621,48.2407774556703)
		metric=Polygon([
			(x,y),(x+20,y),(x+20,y+20),(x,y+20)],
			holes=[[
				(x+10,y+5),(x+10+1e-10,y+5),
				(x+10+1e-10,y+12),(x+10,y+12)]])
		source=_input_feature("persist-edge",box(x-2,y-2,x+22,y+22))
		with patch("scripts.clip_cgal_with_sis.sis_mask",return_value=metric):
			from collections import Counter
			result=_clip_feature(source,None,TO_METRIC,TO_WGS,Counter())
		self.assertEqual(result["properties"]["edge_id"],"persist-edge")
		self.assertTrue(result["properties"]["sis_clipped"])
		self.assertTrue(result["properties"]["wgs84_projection_repaired"])
		self.assertTrue(shape(result["geometry"]).is_valid)


class InputMetricProjectionTests(unittest.TestCase):
	def test_tiny_original_hole_collapsed_in_metric_is_restored(self):
		x,y=16.34,48.21
		original=Polygon([(x,y),(x+.01,y),(x+.01,y+.01),(x,y+.01)],
			holes=[[(x+.004,y+.003),(x+.0040000000001,y+.003),
				(x+.0040000000001,y+.006),(x+.004,y+.006)]])
		self.assertTrue(original.is_valid)
		outer=transform(TO_METRIC,Polygon(original.exterior))
		q=outer.bounds
		projected=Polygon(outer.exterior,holes=[[
			(q[0]+20,q[1]+20),(q[0]+20,q[1]+20),
			(q[0]+20,q[1]+50),(q[0]+20,q[1]+50)]])
		self.assertFalse(projected.is_valid)
		result=_recover_collapsed_metric_input(original,projected)
		self.assertIsNotNone(result)
		fixed,details=result
		self.assertTrue(fixed.is_valid)
		self.assertEqual(details["removed_holes"],1)
		self.assertLess(details["removed_source_geodesic_area_m2"],0.01)

	def test_significant_source_hole_is_never_removed(self):
		x,y=16.34,48.21
		original=Polygon([(x,y),(x+.01,y),(x+.01,y+.01),(x,y+.01)],
			holes=[[(x+.003,y+.003),(x+.005,y+.003),
				(x+.005,y+.006),(x+.003,y+.006)]])
		self.assertTrue(original.is_valid)
		outer=transform(TO_METRIC,Polygon(original.exterior))
		q=outer.bounds
		projected=Polygon(outer.exterior,holes=[[
			(q[0]+20,q[1]+20),(q[0]+20,q[1]+20),
			(q[0]+20,q[1]+50),(q[0]+20,q[1]+50)]])
		self.assertIsNone(_recover_collapsed_metric_input(original,projected))


class MetricSelfIntersectionRepairTests(unittest.TestCase):
	def test_accept_zero_area_repair_even_if_roundtrip_differs_from_source(self):
		# A doubled-back narrow spike makes the ring invalid yet
		# occupies no area. make_valid drops it without changing its
		# footprint. Mock only GEOS's wording ("Ring Self-intersection"
		# vs "Self-intersection") to reach the same production branch.
		x,y=16.34,48.21
		d=.001
		original=box(x,y,x+d,y+d)
		spike=Polygon([(x,y),(x+d,y),(x+d,y+d),
			(x+d/2,y+d),(x+d/2,y+d/2),
			(x+d/2,y+d),(x,y+d)])
		self.assertFalse(spike.is_valid)
		with patch("scripts.clip_cgal_with_sis.explain_validity",
				return_value="Self-intersection[test]"):
			with patch("scripts.clip_cgal_with_sis.make_valid",
					return_value=original):
				result=_repair_metric_self_intersection(
						box(x+0.01,y,x+d+0.01,y+d),
						spike,lambda x,y:(x,y))
		self.assertIsNotNone(result)
		repaired,details=result
		self.assertTrue(repaired.equals(original))
		self.assertAlmostEqual(details["changed_geodesic_area_m2"],0,places=8)
		self.assertEqual(details["change_budget_m2"],0.01)
		self.assertIsNone(details["failure"])

	def test_reject_relocated_area_even_when_total_area_is_equal(self):
		source=box(16.34,48.21,16.341,48.211)
		shifted=box(16.345,48.21,16.346,48.211)
		self.assertAlmostEqual(source.area,shifted.area,places=12)
		bowtie=Polygon([
			(16.34,48.21),(16.341,48.211),
			(16.34,48.211),(16.341,48.21)])
		with patch("scripts.clip_cgal_with_sis.make_valid",return_value=shifted):
			result=_repair_metric_self_intersection(
				source,bowtie,lambda x,y:(x,y))
		self.assertIsNone(result[0])
		self.assertEqual(result[1]["failure"],"changed_area_exceeds_budget")


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
