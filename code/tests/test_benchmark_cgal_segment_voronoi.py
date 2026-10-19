"""Test CGAL input serialization and subprocess failure handling without CGAL installed."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.benchmark_cgal_segment_voronoi import _payload, _run


class CGALBenchmarkTests(unittest.TestCase):
	def test_payload_preserves_segments_and_frame(self):
		segments=[((0,0),(1000,0))]
		frame=[(0.,0.),(2.,0.),(2.,2.),(0.,2.)]
		lines=_payload(segments,frame,dx=1,dy=2).splitlines()
		self.assertEqual(lines[0],"1 2 1001 2")
		self.assertEqual(lines[1],"1 2 2001 2")
		self.assertEqual(lines[-1],"1 2002 1 2")
		self.assertEqual(len(lines),5)

	def test_empty_frame_does_not_add_sites(self):
		self.assertEqual(_payload([((1,2),(3,4))]),"1 2 3 4\n")

	def test_reject_zero_segment(self):
		with self.assertRaises(ValueError):
			_payload([((1,2),(1,2))])

	def test_subprocess_json_status(self):
		with tempfile.TemporaryDirectory() as tmp:
			script=Path(tmp)/"fake_cgal"
			script.write_text("#!"+sys.executable+
				"\nprint('{\"status\":\"ok\",\"construct_s\":0.01}')\n",
				encoding="utf-8")
			script.chmod(0o755)
			result=_run(script,"0 0 1 1\n",2,False)
			self.assertEqual(result["status"],"ok")
			self.assertEqual(result["construct_s"],0.01)


if __name__=="__main__":
	unittest.main()
