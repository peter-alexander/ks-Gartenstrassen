"""Persist Voronoi polygonization independently of later site attribution."""
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from shapely.geometry import LineString,box

from scripts.cgal_geometry_checkpoint import (
	checkpoint_path,save_checkpoint,load_checkpoint)


class GeometryCheckpointTests(unittest.TestCase):
	def test_roundtrip_validated_polygon_and_site_cache(self):
		with TemporaryDirectory() as root:
			file=checkpoint_path(Path(root)/"pre_sis.geojson")
			expected={"schema":"test-v1","linear_use_sha256":"abc"}
			faces=[box(0,0,5,5),box(5,0,10,5)]
			sites=[(10,"edge-a",LineString([(1,1),(4,1)])),
				(12,"edge-b",LineString([(6,1),(9,1)]))]
			save_checkpoint(file,expected,faces,sites,
				{"native_point_sites_omitted":1},{"S":2},
				{"candidates":2},2)
			self.assertTrue(file.is_file())
			loaded=load_checkpoint(file,expected)
			self.assertEqual(len(loaded[0]),2)
			self.assertTrue(loaded[0][0].equals(faces[0]))
			self.assertEqual([s[1] for s in loaded[1]],["edge-a","edge-b"])
			self.assertEqual(loaded[1][0][0],10)
			self.assertTrue(loaded[1][1][2].equals(sites[1][2]))
			self.assertEqual(loaded[2]["native_point_sites_omitted"],1)
			self.assertEqual(loaded[3]["S"],2)
			self.assertEqual(loaded[4]["candidates"],2)
			self.assertEqual(loaded[5],2)
			with self.assertRaisesRegex(ValueError,"veraltet"):
				load_checkpoint(file,{"schema":"test-v1",
					"linear_use_sha256":"changed"})
			with self.assertRaises(FileExistsError):
				save_checkpoint(file,expected,faces,sites,
					{}, {}, {}, 2)

	def test_rejects_truncated_tables(self):
		with TemporaryDirectory() as root:
			file=Path(root)/"geometry.sqlite"
			save_checkpoint(file,{"schema":"test-v1"},
				[box(0,0,1,1)],
				[(1,"a",LineString([(0,0),(1,1)]))],
				{}, {}, {}, 1)
			with sqlite3.connect(file) as db:
				db.execute("DELETE FROM segment_sites")
			with self.assertRaisesRegex(ValueError,"unvollständig"):
				load_checkpoint(file,{"schema":"test-v1"})


if __name__=="__main__":
	unittest.main()
