"""Regression tests for pinpointing malformed native CGAL CCB geometry."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.inspect_cgal_native_face import analyze_face,extract_face


def _native_ring(coords,site="1000 0 2000 0"):
	lines=[f"F {site}\n"]
	for a,b in zip(coords,coords[1:]+coords[:1]):
		lines.extend([
			f"H {a[0]} {a[1]} {b[0]} {b[1]}\n",
			f"S {a[0]} {a[1]} {b[0]} {b[1]}\n",
			"E\n",
		])
	lines.append("Z\n")
	return lines


class NativeFaceInspectionTests(unittest.TestCase):
	def test_extract_exact_face_from_larger_stream(self):
		with TemporaryDirectory() as root:
			path=Path(root)/"faces.txt"
			first=_native_ring([(0,0),(10000,0),(10000,10000),(0,10000)])
			second=_native_ring([(20000,0),(30000,0),(30000,10000),
				(20000,10000)])
			path.write_text("".join(first+second),encoding="utf-8")
			self.assertEqual(extract_face(path,1),first)
			self.assertEqual(extract_face(path,2),second)
			with self.assertRaisesRegex(ValueError,"not found"):
				extract_face(path,3)

	def test_valid_square_ring(self):
		data,ring,edges=analyze_face(_native_ring([
			(0,0),(10000,0),(10000,10000),(0,10000)]),(0.,0.))
		self.assertTrue(data["polygon_valid"])
		self.assertAlmostEqual(data["polygon_area_m2"],100.)
		self.assertEqual(data["halfedge_count"],4)
		self.assertEqual(len(edges),4)
		self.assertTrue(data["repair_applied"] is False)
		self.assertEqual(ring[0],ring[-1])

	def test_self_crossing_ring_is_diagnosed_but_not_repaired(self):
		data,ring,_=analyze_face(_native_ring([
			(0,0),(10000,10000),(0,10000),(10000,0)]),(0.,0.))
		self.assertFalse(data["polygon_valid"])
		self.assertIn("Self-intersection",data["validity_reason"])
		self.assertEqual(data["diagnostic_make_valid_only"]["geometry_type"],
			"MultiPolygon")
		self.assertFalse(data["repair_applied"])
		self.assertEqual(len(ring),5)

	def test_backtracking_zero_area_spike_is_detected(self):
		data,_,_=analyze_face(_native_ring([
			(0,0),(10000,0),(10000,10000),(15000,10000),
			(10000,10000),(0,10000)]),(0.,0.))
		self.assertEqual(data["exact_backtracks"],1)
		self.assertFalse(data["polygon_valid"])

	def test_unclosed_halfedge_chain_is_not_silently_fixed(self):
		lines=["F 1000 0 2000 0\n",
			"H 0 0 10000 0\n","S 0 0 10000 0\n","E\n",
			"H 10000 0 10000 10000\n",
			"S 10000 0 10000 10000\n","E\n","Z\n"]
		with self.assertRaisesRegex(ValueError,"too few ring points"):
			analyze_face(lines,(0,0))


if __name__=="__main__":
	unittest.main()
