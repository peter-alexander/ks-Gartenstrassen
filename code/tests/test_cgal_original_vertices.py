"""Original A-B-C-D-E-F gives point Faces only at B/C/D/E."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from shapely.geometry import LineString,box

from scripts.cgal_original_vertices import original_inner_point_owners
from scripts.cgal_native_face_preview import write_preview
from scripts.cgal_native_faces import read_native_faces


def _face(kind,x,*,a=None,b=None):
	# Tiny square around a site; CCB topology is synthetic but valid.
	ring=[(x-1000,-1000),(x+1000,-1000),
		(x+1000,1000),(x-1000,1000)]
	if kind=="P":
		lines=[f"P {x} 0\n"]
	else:
		lines=[f"F {a} 0 {b} 0\n"]
	for start,end in zip(ring,ring[1:]+ring[:1]):
		lines.append(f"H {start[0]} {start[1]} {end[0]} {end[1]}\n")
		lines.append(f"S {start[0]} {start[1]} {end[0]} {end[1]}\nE\n")
	lines.append("Z\n")
	return "".join(lines)


class OriginalPointSiteSelectionTests(unittest.TestCase):
	def test_a_b_c_d_e_f_only_b_c_d_e(self):
		records=[("object-1","line-17",
			LineString([(0,0),(10,0),(20,0),(30,0),(40,0),(50,0)]))]
		owners,stats=original_inner_point_owners(records,(0,0))
		self.assertEqual(
			owners,{(10000,0):"line-17",(20000,0):"line-17",
				(30000,0):"line-17",(40000,0):"line-17"})
		self.assertEqual(stats["original_interior_vertex_occurrences"],4)
		self.assertEqual(stats["unique_inner_original_vertices"],4)
		self.assertNotIn((0,0),owners)
		self.assertNotIn((50000,0),owners)

	def test_new_noding_only_points_not_in_original_vertex_index(self):
		records=[("o","main",LineString([(0,0),(10,0),(20,10)]))]
		owners,_=original_inner_point_owners(records,(0,0))
		self.assertEqual(owners,{(10000,0):"main"})
		self.assertNotIn((5000,0),owners)

	def test_same_coordinate_with_multiple_edge_ids_remains_unassigned(self):
		records=[
			("o1","a",LineString([(0,0),(10,0),(20,0)])),
			("o2","b",LineString([(10,0),(15,10)]))]
		owners,stats=original_inner_point_owners(records,(0,0))
		self.assertEqual(owners,{})
		self.assertEqual(stats["ambiguous_or_endpoint_coincident_vertices_omitted"],1)

	def test_quantized_consecutive_duplicate_does_not_create_point_site(self):
		records=[("o","a",
			LineString([(0,0),(.0004,0),(1,0),(2,0)]))]
		owners,stats=original_inner_point_owners(records,(0,0))
		self.assertEqual(owners,{(1000,0):"a"})
		self.assertEqual(stats["consecutive_vertices_collapsed_to_mm"],1)

	def test_preview_exports_segment_and_only_original_middle_point(self):
		records=[("o","a",LineString([(0,0),(10,0),(20,0)]))]
		point_owners,_=original_inner_point_owners(records,(0,0))
		with TemporaryDirectory() as root:
			root=Path(root)
			stream=root/"native.txt"
			stream.write_text(
				_face("F",5000,a=0,b=10000)
				+_face("F",15000,a=10000,b=20000)
				+_face("P",0)
				+_face("P",10000)
				+_face("P",20000),encoding="utf-8")
			out=root/"point-selection__preview.geojson"
			report=root/"point-selection__preview_report.json"
			summary=write_preview(stream,{
				((0,0),(10000,0)):"a",
				((10000,0),(20000,0)):"a"},
				(0,0),box(-5,-5,25,5),out,report,
				point_owners=point_owners)
			features=json.loads(out.read_text())["features"]
			self.assertEqual(len(features),3)
			self.assertEqual(sorted(f["properties"]["generator_type"]
				for f in features),["inner_point","segment","segment"])
			self.assertEqual([f["properties"]["edge_id"] for f in features],
				["a","a","a"])
			self.assertEqual(summary["stats"]["point_faces_exported"],1)
			self.assertEqual(summary["stats"][
				"point_faces_without_inner_original_vertex_omitted"],2)

	def test_strict_reader_selects_same_original_middle_point(self):
		records=[("o","a",LineString([(0,0),(10,0),(20,0)]))]
		point_owners,_=original_inner_point_owners(records,(0,0))
		with TemporaryDirectory() as root:
			stream=Path(root)/"native.txt"
			stream.write_text(_face("F",5000,a=0,b=10000)
				+_face("P",0)+_face("P",10000)+_face("P",20000),
				encoding="utf-8")
			groups,stats=read_native_faces(stream,
				{((0,0),(10000,0)):"a"},(0,0),
				box(-5,-5,25,5),point_owners=point_owners)
			self.assertEqual(len(groups["a"]),2)
			self.assertEqual(stats["segment_faces_inside_window"],1)
			self.assertEqual(stats["point_faces_inside_window"],1)
			self.assertEqual(stats[
				"point_faces_without_inner_original_vertex_omitted"],2)


if __name__=="__main__":
	unittest.main()
