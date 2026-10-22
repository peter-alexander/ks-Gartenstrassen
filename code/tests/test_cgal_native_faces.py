"""Test native CCB halfedge-based polygon reconstruction, no site joins."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from shapely.geometry import box, Polygon

from scripts.cgal_native_faces import _join_halfedge,read_native_faces
from scripts.build_cgal_native_faces_pre_sis import _dissolve


def square_site(x0,y0,x1,y1,site_x0,site_x1,*,reversed_chord=False):
	coords=[(x0,y0),(x1,y0),(x1,y1),(x0,y1)]
	out=[f"F {site_x0} 0 {site_x1} 0"]
	for i in range(4):
		a=coords[i]
		b=coords[(i+1)%4]
		out.append(f"H {a[0]} {a[1]} {b[0]} {b[1]}")
		if reversed_chord:
			a,b=b,a
		out.append(f"S {a[0]} {a[1]} {b[0]} {b[1]}")
		out.append("E")
	out.append("Z")
	return "\n".join(out)+"\n"


class NativeVoronoiFaceTests(unittest.TestCase):
	def test_two_adjacent_native_faces_dissolve_by_same_original_id(self):
		with TemporaryDirectory() as tmp:
			path=Path(tmp)/"faces.txt"
			path.write_text(
				square_site(0,0,10000,10000,1000,2000)
				+square_site(10000,0,20000,10000,2000,3000,
					reversed_chord=True),encoding="utf-8")
			owners={
				((1000,0),(2000,0)):"same-edge",
				((2000,0),(3000,0)):"same-edge"}
			groups,stats=read_native_faces(path,owners,(0,0),
				box(0,0,20,10))
			self.assertEqual(stats["native_face_records"],2)
			self.assertEqual(stats["segment_faces_inside_window"],2)
			self.assertEqual(list(groups),["same-edge"])
			dissolved=list(_dissolve(groups))
			self.assertEqual(len(dissolved),1)
			self.assertEqual(dissolved[0][0],"same-edge")
			self.assertAlmostEqual(dissolved[0][1].area,200)

	def test_point_faces_not_present_and_frame_site_is_not_attributed(self):
		with TemporaryDirectory() as tmp:
			path=Path(tmp)/"faces.txt"
			path.write_text(
				square_site(0,0,10000,10000,1000,2000)
				+square_site(10000,0,20000,10000,-5000,-6000),
				encoding="utf-8")
			groups,stats=read_native_faces(path,
				{((1000,0),(2000,0)):"real"},(0,0),box(0,0,20,10))
			self.assertEqual(stats["frame_faces_omitted"],1)
			self.assertEqual(len(groups["real"]),1)
			self.assertEqual(stats["segment_faces_inside_window"],1)

	def test_disconnected_faces_with_same_id_remain_distinct(self):
		with TemporaryDirectory() as tmp:
			path=Path(tmp)/"faces.txt"
			path.write_text(
				square_site(0,0,10000,10000,1000,2000)
				+square_site(30000,0,40000,10000,3000,4000),
				encoding="utf-8")
			owners={((1000,0),(2000,0)):"e",
				((3000,0),(4000,0)):"e"}
			groups,_=read_native_faces(path,owners,(0,0),box(0,0,40,10))
			self.assertEqual(len(list(_dissolve(groups))),2)

	def test_invalid_native_face_provably_outside_aoi_is_ignored(self):
		# Deliberately self-crossing bow-tie polygon. Its envelope is
		# wholly west of the AOI; validity must not block usable Vienna faces.
		with TemporaryDirectory() as tmp:
			path=Path(tmp)/"faces.txt"
			invalid="".join([
				"F 1000 0 2000 0\n",
				"H 0 0 10000 10000\nS 0 0 10000 10000\nE\n",
				"H 10000 10000 0 10000\nS 10000 10000 0 10000\nE\n",
				"H 0 10000 10000 0\nS 0 10000 10000 0\nE\n",
				"H 10000 0 0 0\nS 10000 0 0 0\nE\n",
				"Z\n",
			])
			path.write_text(invalid+square_site(
				20000,0,30000,10000,3000,4000),encoding="utf-8")
			groups,stats=read_native_faces(path,{
				((1000,0),(2000,0)):"outside-invalid",
				((3000,0),(4000,0)):"inside-valid",
			},(0,0),box(20,0,30,10))
			self.assertEqual(list(groups),["inside-valid"])
			self.assertEqual(stats["segment_faces_outside_aoi_bbox"],1)
			self.assertEqual(stats["segment_faces_inside_window"],1)

	def test_invalid_native_face_overlapping_aoi_still_rejected(self):
		# We must NOT conceal broken polygons within the study area.
		with TemporaryDirectory() as tmp:
			path=Path(tmp)/"faces.txt"
			path.write_text(
				"F 1000 0 2000 0\n"
				"H 0 0 10000 10000\nS 0 0 10000 10000\nE\n"
				"H 10000 10000 0 10000\nS 10000 10000 0 10000\nE\n"
				"H 0 10000 10000 0\nS 0 10000 10000 0\nE\n"
				"H 10000 0 0 0\nS 10000 0 0 0\nE\n"
				"Z\n",encoding="utf-8")
			with self.assertRaisesRegex(ValueError,"Self-intersection"):
				read_native_faces(path,{((1000,0),(2000,0)):"invalid"},
					(0,0),box(0,0,10,10))

	def test_clips_to_actual_aoi_not_only_its_bounding_rectangle(self):
		with TemporaryDirectory() as tmp:
			path=Path(tmp)/"faces.txt"
			path.write_text(square_site(0,0,20000,20000,1000,2000))
			# U-shaped study polygon, with a large interior notch.
			aoi=Polygon([(0,0),(20,0),(20,20),(15,20),
				(15,5),(5,5),(5,20),(0,20)])
			groups,stats=read_native_faces(path,
				{((1000,0),(2000,0)):"edge"},
				(0,0),aoi)
			self.assertEqual(stats["segment_faces_inside_window"],1)
			self.assertTrue(groups["edge"][0].equals(aoi))

	def test_broken_face_halfedge_is_rejected(self):
		with self.assertRaisesRegex(ValueError,"weicht"):
			_join_halfedge([((0,0),(1,0))],(0,0),(5,0),
				face_number=1,halfedge_number=1)

	def test_nonclosed_ring_is_rejected(self):
		with TemporaryDirectory() as tmp:
			path=Path(tmp)/"faces.txt"
			path.write_text("F 1000 0 2000 0\n"
				"H 0 0 10000 0\nS 0 0 10000 0\nE\n"
				"H 10000 0 10000 10000\nS 10000 0 10000 10000\nE\n"
				"Z\n")
			with self.assertRaisesRegex(ValueError,"CCB nicht geschlossen"):
				read_native_faces(path,{((1000,0),(2000,0)):"a"},
					(0,0),box(0,0,20,20))


if __name__=="__main__":
	unittest.main()
