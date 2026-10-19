"""CGAL dual primitives: reject bad records, ignore only zero-length S fragments."""
import tempfile
import unittest
from pathlib import Path

from shapely.geometry import LineString, box

from scripts.build_cgal_voronoi_geojson import _read_dual_lines, _record_line


class CgalDualLinesTests(unittest.TestCase):
	def setUp(self):
		self.window=box(-10,-10,10,10)

	def test_zero_length_segment_is_not_a_valid_shapely_line(self):
		self.assertIsNone(_record_line("S",((3.,4.),(3.,4.)),
			self.window))

	def test_nonzero_segment_is_preserved(self):
		line=_record_line("S",((0.,0.),(5.,0.)),self.window)
		self.assertIsInstance(line,LineString)
		self.assertAlmostEqual(line.length,5.)

	def test_degenerate_fragments_are_counted(self):
		with tempfile.TemporaryDirectory() as temp:
			path=Path(temp)/"dual.txt"
			path.write_text("S 1000 1000 1000 1000\n"
				"S 0 0 5000 0\n",encoding="utf-8")
			lines,stats=_read_dual_lines(path,self.window,(0.,0.))
		self.assertEqual(len(lines),1)
		self.assertEqual(stats["S"],2)
		self.assertEqual(stats["degenerate_S"],1)
		self.assertEqual(stats["clipped"],1)

	def test_invalid_ray_reports_line_number(self):
		with tempfile.TemporaryDirectory() as temp:
			path=Path(temp)/"dual.txt"
			path.write_text("S 0 0 5000 0\nR 0 0 0 0\n",
				encoding="utf-8")
			with self.assertRaisesRegex(ValueError,"Zeile 2"):
				_read_dual_lines(path,self.window,(0.,0.))

	def test_nonfinite_coordinate_is_rejected(self):
		with tempfile.TemporaryDirectory() as temp:
			path=Path(temp)/"dual.txt"
			path.write_text("S nan 0 1000 0\n",encoding="utf-8")
			with self.assertRaisesRegex(ValueError,"Zeile 1"):
				_read_dual_lines(path,self.window,(0.,0.))


if __name__=="__main__":
	unittest.main()
