"""Offline tests for 20 m GIP line-neighborhood diagnosis."""
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from shapely.geometry import LineString, box
from shapely.wkb import dumps

from scripts.diagnose_parallel_gip import Axis, find_parallel_pairs, read_axes, run, require_complete_wien


def edge(gid, points, *, name="Hauptstraße", fow=3, start="s", end="e"):
	return Axis(gid, name, fow, start, end, LineString(points))


class GIPParallelTests(unittest.TestCase):
	def test_parallel_reversed_directions_at_20_meters(self):
		a = edge("a", [(0, 0), (100, 0)])
		b = edge("b", [(100, 19), (0, 19)], fow=2)
		pairs, n = find_parallel_pairs([a, b])
		self.assertEqual(n, 1)
		self.assertEqual(len(pairs), 1)
		self.assertEqual((pairs[0]["cover_a"], pairs[0]["cover_b"]), (1.0, 1.0))
		self.assertEqual((pairs[0]["fow_a"], pairs[0]["fow_b"]), (3, 2))

	def test_excludes_just_beyond_twenty_meters(self):
		a = edge("a", [(0, 0), (100, 0)])
		b = edge("b", [(0, 20.1), (100, 20.1)])
		pairs, n = find_parallel_pairs([a, b])
		self.assertEqual(n, 0)
		self.assertEqual(pairs, [])

	def test_perpendicular_crossing_is_not_parallel(self):
		a = edge("a", [(-50, 0), (50, 0)])
		b = edge("b", [(0, -50), (0, 50)])
		pairs, n = find_parallel_pairs([a, b])
		self.assertEqual(n, 1)
		self.assertEqual(pairs, [])

	def test_short_collinear_end_to_end_is_not_parallel(self):
		a = edge("a", [(0, 0), (100, 0)])
		b = edge("b", [(100, 0), (200, 0)])
		pairs, n = find_parallel_pairs([a, b])
		self.assertEqual(n, 1)
		self.assertEqual(pairs, [])

	def test_long_enough_overlap_passes_symmetric_coverage(self):
		a = edge("a", [(0, 0), (100, 0)])
		b = edge("b", [(25, 10), (115, 10)], name="Radweg")
		pairs, _ = find_parallel_pairs([a, b])
		self.assertEqual(len(pairs), 1)
		self.assertFalse(pairs[0]["same_name"])

	def test_small_overlap_does_not_pass(self):
		a = edge("a", [(0, 0), (100, 0)])
		b = edge("b", [(50, 10), (150, 10)])
		pairs, _ = find_parallel_pairs([a, b])
		self.assertEqual(pairs, [])

	def test_read_only_index_and_geojson_export(self):
		with TemporaryDirectory() as tmp:
			base = Path(tmp)
			index = base / "gip.sqlite"
			with sqlite3.connect(index) as db:
				db.execute("CREATE TABLE meta (key TEXT, value TEXT)")
				db.execute("INSERT INTO meta VALUES ('crs', '\"EPSG:31256\"')")
				db.execute("CREATE TABLE axes (gip TEXT,name TEXT,fow INTEGER,node_from TEXT,node_to TEXT,wkb BLOB)")
				for a in (edge("a", [(0,0),(100,0)]), edge("b", [(100,15),(0,15)])):
					db.execute("INSERT INTO axes VALUES (?,?,?,?,?,?)",
						(a.id,a.name,a.fow,a.start,a.end,dumps(a.geom)))
			before = index.read_bytes()
			out = base / "report"
			result = run(index, out)
			self.assertEqual(result["akzeptierte_paare"], 1)
			self.assertEqual(len(read_axes(index)), 2)
			self.assertEqual(index.read_bytes(), before)
			features = json.loads((out / "parallelpaare.geojson").read_text())
			self.assertEqual(len(features["features"]), 2)
			self.assertEqual(features["features"][0]["properties"]["gruppe"], 1)
			with self.assertRaises(FileExistsError):
				run(index, out)


	def test_wien_validation_rejects_pilot_and_wrong_index(self):
		with TemporaryDirectory() as tmp:
			index = Path(tmp) / "gip.sqlite"
			manifest = Path(tmp) / "raster.json"
			manifest.write_text("synthetic checksum source")
			with sqlite3.connect(index) as db:
				db.execute("CREATE TABLE meta (key TEXT, value TEXT)")
				db.execute("CREATE TABLE axes (gip TEXT)")
				db.executemany("INSERT INTO axes VALUES (?)",
					((str(i),) for i in range(10_000)))
				db.executemany("INSERT INTO meta VALUES (?,?)", (
					("manifest_sha256", json.dumps("verified")),
					("achsen", json.dumps(10_000)),
					("crs", json.dumps("EPSG:31256")),
				))
			tiles = [{"id": i} for i in range(500)]
			with patch("scripts.diagnose_parallel_gip.checksum", return_value="verified"):
				with patch("scripts.diagnose_parallel_gip.read_manifest",
						return_value=({"tiles": tiles}, box(0, 0, 1000, 1000))):
					with self.assertRaisesRegex(ValueError, "Kein Wien-Gesamtgebiet"):
						require_complete_wien(index, manifest)
				with patch("scripts.diagnose_parallel_gip.read_manifest",
						return_value=({"tiles": tiles}, box(0, 0, 20000, 20000))):
					self.assertEqual(require_complete_wien(index, manifest)["axes"], 10_000)
			with patch("scripts.diagnose_parallel_gip.read_manifest",
					return_value=({"tiles": tiles}, box(0, 0, 20000, 20000))):
				with self.assertRaisesRegex(ValueError, "gehört nicht"):
					require_complete_wien(index, manifest)


if __name__ == "__main__":
	unittest.main()
