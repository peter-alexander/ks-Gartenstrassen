"""CGAL selected segment + inner-point native preview -> Polygon per edge_id.

Tests use real EPSG:4326 coordinates near Vienna; the dissolve itself
projects to EPSG:31256 and returns valid WGS84 polygons, never creates
MultiPolygon as a regular result.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from shapely.geometry import Polygon,LineString,box,mapping,shape
from shapely.ops import transform
from pyproj import Transformer

from scripts.dissolve_cgal_preview import dissolve


def _feature(edge_id,number,geometry,*,kind="segment",fallback=False):
	return {"type":"Feature","properties":{
		"edge_id":edge_id,"face_number":number,"generator_type":kind,
		"fallback":fallback,"fallback_count":1 if fallback else 0,
		"preview_only":True,"not_validated":True},
		"geometry":mapping(geometry)}


def _write_source(path,features,*,point_mode="original_inner_only"):
	with path.open("w",encoding="utf-8") as writer:
		writer.write('{"type":"FeatureCollection","features":[\n')
		for i,feature in enumerate(features):
			if i:
				writer.write(",\n")
			writer.write(json.dumps(feature,separators=(",",":")))
		writer.write('\n],"metadata":{"schema":"native-cgal-faces-raw-preview-v1",'
			'"geometry_validated":false,"point_faces_assigned":"'
			+point_mode+'"}}\n')


def _square(x0,y0,x1,y1):
	return box(x0,y0,x1,y1)


class PreviewDissolveTests(unittest.TestCase):
	def _run(self,root,features,*,hulls=None,replace_existing=False):
		root=Path(root)
		preview=root/"source__preview.geojson"
		_write_source(preview,features)
		out=root/"dissolved.geojson"
		debug=root/"debug.geojson"
		report=root/"report.json"
		summary=dissolve(preview,out,debug,report,
			junction_hulls=hulls,replace_existing=replace_existing)
		return (json.loads(out.read_text()),
			json.loads(debug.read_text()),json.loads(report.read_text()),
			summary,preview,out,debug,report)

	def test_adjacent_segment_and_inner_point_faces_yield_one_polygon(self):
		with TemporaryDirectory() as root:
			a=_square(16.300,48.200,16.301,48.201)
			b=_square(16.301,48.200,16.302,48.201)
			c=_square(16.302,48.200,16.303,48.201)
			valid,debug,report,stats,source,out,_,_=self._run(root,[
				_feature("edge-A",3,c,kind="segment"),
				_feature("edge-A",1,a,kind="segment"),
				_feature("edge-A",2,b,kind="inner_point")])
			self.assertEqual(len(valid["features"]),1)
			result=valid["features"][0]
			self.assertEqual(result["geometry"]["type"],"Polygon")
			self.assertEqual(result["properties"]["edge_id"],"edge-A")
			self.assertEqual(result["properties"]["source_face_count"],3)
			self.assertEqual(result["properties"]["segment_face_count"],2)
			self.assertEqual(result["properties"]["inner_point_face_count"],1)
			self.assertTrue(shape(result["geometry"]).is_valid)
			self.assertAlmostEqual(shape(result["geometry"]).area,
				a.area+b.area+c.area,places=10)
			self.assertEqual(debug["features"],[])
			self.assertEqual(report["failures"],[])
			self.assertEqual(stats["statistics"]["merged_polygons"],1)
			with self.assertRaises(FileExistsError):
				dissolve(source,out,Path(root)/"other_debug.geojson",
					Path(root)/"other_report.json")

	def test_disconnected_same_id_is_only_in_debug_with_all_sources(self):
		with TemporaryDirectory() as root:
			a=_square(16.300,48.20,16.301,48.201)
			b=_square(16.310,48.20,16.311,48.201)
			good=_square(16.320,48.20,16.321,48.201)
			valid,debug,report,_,*_=self._run(root,[
				_feature("disjoint",5,a),
				_feature("disjoint",6,b,kind="inner_point"),
				_feature("good",7,good)])
			self.assertEqual([f["properties"]["edge_id"]
				for f in valid["features"]],["good"])
			self.assertEqual(len(debug["features"]),2)
			self.assertEqual({f["properties"]["edge_id"]
				for f in debug["features"]},{"disjoint"})
			self.assertEqual({f["properties"]["dissolve_error"]
				for f in debug["features"]},{"not_contiguous"})
			self.assertEqual(report["failures"][0]["face_numbers"],[5,6])
			self.assertIn("2 getrennte Polygone",report["failures"][0]["detail"])

	def test_non_polygon_source_goes_to_debug(self):
		with TemporaryDirectory() as root:
			valid,debug,report,_,*_=self._run(root,[
				_feature("bad",2,
					LineString([(16.3,48.2),(16.31,48.21)])),
				_feature("good",3,_square(16.30,48.20,16.31,48.21))])
			self.assertEqual(len(valid["features"]),1)
			self.assertEqual(len(debug["features"]),1)
			self.assertEqual(report["failures"][0]["reason"],"source_not_polygon")

	def test_invalid_bowtie_source_not_automatically_repaired(self):
		with TemporaryDirectory() as root:
			bowtie=Polygon([(16.300,48.200),(16.303,48.203),
				(16.300,48.203),(16.303,48.200)])
			valid,debug,report,_,*_=self._run(root,[
				_feature("invalid",1,bowtie),
				_feature("valid",2,_square(16.33,48.23,16.34,48.24))])
			self.assertEqual(len(valid["features"]),1)
			self.assertEqual(len(debug["features"]),1)
			self.assertEqual(report["failures"][0]["reason"],
				"source_invalid_polygon")
			self.assertFalse(shape(debug["features"][0]["geometry"]).is_valid)

	def test_valid_fallback_can_be_merged_but_is_explicitly_marked(self):
		with TemporaryDirectory() as root:
			valid,debug,report,stats,*_=self._run(root,[
				_feature("fallback",1,_square(
					16.30,48.20,16.31,48.21),fallback=True)])
			self.assertEqual(valid["features"][0]["properties"][
				"fallback_face_count"],1)
			self.assertTrue(valid["features"][0]["properties"]["preview_based"])
			self.assertFalse(report["geometrically_assured"])
			self.assertEqual(stats["accepted_fallback_source_faces"],1)
			self.assertEqual(debug["features"],[])

	def test_turn_use_convex_hull_is_cut_from_individual_faces_before_union(self):
		with TemporaryDirectory() as root:
			a=_square(16.300,48.200,16.302,48.202)
			b=_square(16.302,48.200,16.304,48.202)
			# Local convex intersection envelope covers the shared
			# boundary at its upper side, leaving a connected polygon.
			to_metric=Transformer.from_crs(
				4326,31256,always_xy=True).transform
			hull=transform(to_metric,_square(
				16.3015,48.2014,16.3025,48.2021))
			valid,debug,report,stats,*_=self._run(root,[
				_feature("a",1,a),
				_feature("a",2,b,kind="inner_point")],
				hulls=[("node-1",hull)])
			self.assertEqual(len(valid["features"]),1)
			self.assertEqual(valid["features"][0]["geometry"]["type"],"Polygon")
			self.assertEqual(debug["features"],[])
			self.assertTrue(valid["features"][0]["properties"][
				"turn_use_hulls_removed"])
			self.assertEqual(report["turn_use_junctions"]["hull_count"],1)
			self.assertEqual(stats["statistics"]["faces_cut_by_turn_use"],2)
			self.assertGreater(stats["statistics"][
				"turn_use_removed_area_sum_m2"],0)
			joined=shape(valid["features"][0]["geometry"])
			self.assertLess(joined.area,a.area+b.area)

	def test_mask_that_disconnects_one_edge_id_routes_original_faces_to_debug(self):
		with TemporaryDirectory() as root:
			whole=_square(16.300,48.200,16.304,48.202)
			to_metric=Transformer.from_crs(
				4326,31256,always_xy=True).transform
			# A rectangular TURN_USE hull makes two disjoint islands.
			cut=transform(to_metric,_square(
				16.3015,48.1995,16.3025,48.2025))
			valid,debug,report,*_=self._run(root,[
				_feature("split",12,whole)],
				hulls=[("node-1",cut)])
			self.assertEqual(valid["features"],[])
			self.assertEqual(len(debug["features"]),1)
			self.assertEqual(debug["features"][0]["properties"]["edge_id"],
				"split")
			self.assertEqual(debug["features"][0]["properties"][
				"dissolve_error"],"not_contiguous")
			# Debug retains the original source geometry before mask.
			self.assertTrue(shape(debug["features"][0]["geometry"]).equals(whole))
			self.assertEqual(report["failures"][0]["face_numbers"],[12])

	def test_mask_can_remove_whole_source_face_without_crashing(self):
		with TemporaryDirectory() as root:
			whole=_square(16.30,48.20,16.301,48.201)
			to_metric=__import__("pyproj",fromlist=["Transformer"]).Transformer.from_crs(
				4326,31256,always_xy=True).transform
			from shapely.ops import transform
			cut=transform(to_metric,_square(16.29,48.19,16.31,48.21))
			valid,debug,report,stats,*_=self._run(root,[
				_feature("masked",5,whole)],hulls=[("node-5",cut)])
			self.assertEqual(valid["features"],[])
			self.assertEqual(len(debug["features"]),1)
			self.assertEqual(report["failures"][0]["reason"],"empty_union")
			self.assertEqual(stats["statistics"][
				"faces_entirely_removed_by_turn_use"],1)

	def test_existing_previous_outputs_may_be_replaced_explicitly(self):
		with TemporaryDirectory() as root:
			root=Path(root)
			preview=root/"source__preview.geojson"
			a=_square(16.300,48.200,16.301,48.201)
			_write_source(preview,[_feature("a",1,a)])
			out=root/"result.geojson"
			debug=root/"debug.geojson"
			report=root/"report.json"
			for path in (out,debug,report):
				path.write_text("obsolete")
			result=dissolve(preview,out,debug,report,replace_existing=True)
			self.assertEqual(len(json.loads(out.read_text())["features"]),1)
			self.assertEqual(json.loads(debug.read_text())["features"],[])
			self.assertEqual(result["statistics"]["merged_polygons"],1)

	def test_no_silent_acceptance_of_older_segment_only_preview(self):
		with TemporaryDirectory() as root:
			root=Path(root)
			source=root/"segment_only.geojson"
			_write_source(source,[_feature("a",1,
				_square(16.3,48.2,16.31,48.21))],
				point_mode="false")
			with self.assertRaisesRegex(ValueError,"Punkt-Faces"):
				dissolve(source,root/"out.geojson",root/"debug.geojson",
					root/"report.json")
			self.assertFalse((root/"out.geojson").exists())

	def test_empty_preview_and_truncated_preview_fail_without_outputs(self):
		with TemporaryDirectory() as root:
			root=Path(root)
			source=root/"empty.geojson"
			_write_source(source,[])
			with self.assertRaisesRegex(ValueError,"keine Faces"):
				dissolve(source,root/"out.geojson",root/"debug.geojson",
					root/"report.json")
			source.write_text(
				'{"type":"FeatureCollection","features":[\n'
				+json.dumps(_feature("one",1,
					_square(16.3,48.2,16.31,48.21)))+"\n",
				encoding="utf-8")
			with self.assertRaisesRegex(ValueError,"Endabschnitt"):
				dissolve(source,root/"out.geojson",root/"debug.geojson",
					root/"report.json")
			self.assertFalse((root/"out.geojson").exists())


if __name__=="__main__":
	unittest.main()
