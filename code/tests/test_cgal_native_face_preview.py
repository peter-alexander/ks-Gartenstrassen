"""Unchecked CGAL preview must survive failing native halfedges before QA."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from shapely.geometry import Polygon, box

from scripts.cgal_native_face_preview import write_preview


def _face(site_a,site_b,ring,*,bad_halfedge=None):
	lines=[f"F {site_a} 0 {site_b} 0\n"]
	for idx,(a,b) in enumerate(zip(ring,ring[1:]+ring[:1]),1):
		lines.append(f"H {a[0]} {a[1]} {b[0]} {b[1]}\n")
		if idx==bad_halfedge:
			# Deliberately inconsistent native dual chord, as in Face 282.
			lines.append("S 90000 90000 100000 100000\n")
		else:
			lines.append(f"S {a[0]} {a[1]} {b[0]} {b[1]}\n")
		lines.append("E\n")
	lines.append("Z\n")
	return "".join(lines)


class NativePreviewTests(unittest.TestCase):
	def test_writes_all_relevant_cells_even_when_halfedge_fails_strict_join(self):
		with TemporaryDirectory() as root:
			root=Path(root)
			stream=root/"native.txt"
			# Outer frame is omitted. One bad Face inside the AOI must be
			# visualizable with original owner, not silently discarded.
			stream.write_text(
				_face(1,2,[(0,0),(10000,0),(10000,10000),(0,10000)],
					bad_halfedge=1)
				+_face(3,4,[(10000,0),(20000,0),(20000,10000),
					(10000,10000)])
				+_face(5,6,[(100000,0),(110000,0),(110000,10000),
					(100000,10000)])
				+_face(-100,-200,[(0,0),(10000,0),(10000,10000),
					(0,10000)]),
				encoding="utf-8")
			out=root/"preview.geojson"
			report=root/"preview-report.json"
			owners={
				((1,0),(2,0)):"owner-a",
				((3,0),(4,0)):"owner-b",
				((5,0),(6,0)):"owner-out"}
			result=write_preview(stream,owners,(0,0),box(0,0,20,10),
				out,report,identity={"key":"source-A"})
			doc=json.loads(out.read_text(encoding="utf-8"))
			self.assertEqual(doc["type"],"FeatureCollection")
			self.assertEqual(len(doc["features"]),2)
			a,b=doc["features"]
			self.assertEqual(a["properties"]["edge_id"],"owner-a")
			self.assertEqual(a["properties"]["face_number"],1)
			self.assertTrue(a["properties"]["fallback"])
			self.assertEqual(a["properties"]["fallback_count"],1)
			self.assertFalse(b["properties"]["fallback"])
			self.assertTrue(doc["metadata"]["geometry_validated"] is False)
			self.assertEqual(result["stats"]["faces_with_fallback"],1)
			self.assertEqual(result["stats"]["segment_faces_outside_aoi_bbox"],1)
			self.assertEqual(result["stats"]["artificial_frame_faces_omitted"],1)
			self.assertIn("Face 1, Halfedge 1",result["first_issues"][0]["issues"][0]["reason"])
			self.assertEqual(json.loads(report.read_text(encoding="utf-8"))[
				"preview_input_identity"],{"key":"source-A"})
			with self.assertRaises(FileExistsError):
				write_preview(stream,owners,(0,0),box(0,0,20,10),
					out,report)

	def test_retains_invalid_polygon_for_qgis_instead_of_make_valid(self):
		with TemporaryDirectory() as root:
			root=Path(root)
			stream=root/"native.txt"
			stream.write_text(_face(1,2,[(0,0),(10000,10000),
				(0,10000),(10000,0)]),encoding="utf-8")
			out=root/"preview.geojson"
			result=write_preview(stream,{((1,0),(2,0)):"a"},(0,0),
				box(0,0,10,10),out,root/"report.json")
			doc=json.loads(out.read_text(encoding="utf-8"))
			geom=Polygon(doc["features"][0]["geometry"]["coordinates"][0])
			self.assertFalse(geom.is_valid)
			self.assertEqual(result["stats"]["segment_faces_exported"],1)
			self.assertEqual(result["stats"]["faces_with_fallback"],0)

	def test_curved_halfedge_keeps_original_sampled_vertices_if_valid(self):
		with TemporaryDirectory() as root:
			root=Path(root)
			stream=root/"native.txt"
			stream.write_text(
				"F 1 0 2 0\n"
				"H 0 0 10000 0\n"
				"S 0 0 5000 -2000\n"
				"S 5000 -2000 10000 0\n"
				"E\n"
				"H 10000 0 10000 10000\n"
				"S 10000 0 10000 10000\nE\n"
				"H 10000 10000 0 10000\n"
				"S 10000 10000 0 10000\nE\n"
				"H 0 10000 0 0\nS 0 10000 0 0\nE\n"
				"Z\n",encoding="utf-8")
			doc_path=root/"preview.geojson"
			result=write_preview(stream,{((1,0),(2,0)):"curve"},(0,0),
				box(-2,-3,12,12),doc_path,root/"report.json")
			coords=json.loads(doc_path.read_text())["features"][0][
				"geometry"]["coordinates"][0]
			self.assertEqual(len(coords),6)
			self.assertEqual(result["stats"]["faces_with_fallback"],0)

	def test_corrupted_native_stream_is_not_reported_as_completed(self):
		with TemporaryDirectory() as root:
			root=Path(root)
			stream=root/"native.txt"
			stream.write_text("F 1 0 2 0\nH 0 0 10000 0\n")
			out=root/"preview.geojson"
			report=root/"report.json"
			with self.assertRaisesRegex(ValueError,"unvollständig"):
				write_preview(stream,{((1,0),(2,0)):"a"},(0,0),
					box(0,0,10,10),out,report)
			self.assertFalse(out.exists())
			self.assertFalse(report.exists())


if __name__=="__main__":
	unittest.main()
