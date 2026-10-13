import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts.extract_fmzk import (
	DEFAULT_BBOX, build_commands, extract, find_source, gpkg_info, parse_bbox, projected_clip,
)


def minimal_gpkg(path, layer, count=1, srs=31256):
	with sqlite3.connect(path) as conn:
		conn.executescript("""
			CREATE TABLE gpkg_contents (table_name TEXT, srs_id INTEGER);
			CREATE TABLE gpkg_geometry_columns (table_name TEXT, column_name TEXT, srs_id INTEGER);
		""")
		conn.execute("INSERT INTO gpkg_contents VALUES (?, ?)", (layer, srs))
		conn.execute("INSERT INTO gpkg_geometry_columns VALUES (?, ?, ?)", (layer, "geom", srs))
		conn.execute(
			f'CREATE TABLE "{layer}" (id INTEGER PRIMARY KEY, geom BLOB, F_KLASSE INTEGER, F_KLASSE_TEXT TEXT, FMZK_ID INTEGER)'
		)
		for i in range(count):
			conn.execute(
				f'INSERT INTO "{layer}" (id, F_KLASSE, F_KLASSE_TEXT, FMZK_ID) VALUES (?, ?, ?, ?)',
				(i + 1, 21, "Fahrbahn", i + 1),
			)


class ExtractFmzkTest(unittest.TestCase):
	def test_bbox_and_projection(self):
		bbox = parse_bbox(DEFAULT_BBOX)
		self.assertEqual(bbox, (16.361012, 48.221226, 16.366948, 48.224902))
		polygon = projected_clip(bbox)
		self.assertTrue(polygon.is_valid)
		self.assertGreater(polygon.area, 170000)
		self.assertLess(polygon.area, 190000)
		self.assertGreater(len(polygon.exterior.coords), 60)
		for invalid in ("16.4,48.3,16.3,48.4", "16.0,48.2,17.0,48.3", "16,48,17"):
			with self.subTest(invalid=invalid), self.assertRaises(ValueError):
				parse_bbox(invalid)

	def test_ogr2ogr_commands_preserve_metric_crs_and_clip(self):
		polygon = projected_clip(parse_bbox(DEFAULT_BBOX))
		first, second = build_commands(Path("FMZK_WIEN_GP.gpkg"), Path("candidates.gpkg"),
			Path("clipped.gpkg"), polygon, make_valid=True)
		self.assertIn("-spat", first)
		self.assertIn("CONVERT_TO_LINEAR", first)
		self.assertIn("-preserve_fid", first)
		self.assertIn("-makevalid", first)
		self.assertNotIn("-t_srs", first)
		self.assertEqual(second[second.index("-clipsrc") + 1], polygon.wkt)
		self.assertIn("PROMOTE_TO_MULTI", second)
		self.assertNotIn("-makevalid", second)
		self.assertNotIn("-spat_srs", first)

	def test_source_metadata_and_missing_layer(self):
		with tempfile.TemporaryDirectory() as tmp:
			path = Path(tmp) / "test.gpkg"
			minimal_gpkg(path, "FMZK_WIEN_20260112")
			info = gpkg_info(path, "FMZK_WIEN_20260112")
			self.assertEqual(info["geometry_column"], "geom")
			self.assertFalse(info["rtree_present"])
			with self.assertRaises(ValueError):
				gpkg_info(path, "wrong_layer")
			with self.assertRaises(FileNotFoundError):
				find_source(Path(tmp) / "missing.gpkg")

	def test_extract_preserves_source_and_creates_manifest(self):
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			source, output = root / "original.gpkg", root / "processed" / "test.gpkg"
			minimal_gpkg(source, "FMZK_WIEN_20260112", count=2)
			source_bytes = source.read_bytes()
			commands = []

			def fake_run(command, check):
				self.assertTrue(check)
				commands.append(command)
				destination = Path(command[3])
				layer = "fmzk_candidates" if len(commands) == 1 else "fmzk"
				minimal_gpkg(destination, layer, count=2)

			with patch("scripts.extract_fmzk.shutil.which", return_value="/usr/bin/ogr2ogr"), patch(
				"scripts.extract_fmzk.subprocess.run", side_effect=fake_run
			):
				report = extract(source, output, parse_bbox(DEFAULT_BBOX))
			self.assertEqual(len(commands), 2)
			self.assertEqual(report["feature_count"], 2)
			self.assertEqual(report["output_srs"], "EPSG:31256")
			self.assertTrue(output.is_file())
			self.assertEqual(source.read_bytes(), source_bytes)
			manifest = json.loads(output.with_suffix(".json").read_text())
			self.assertEqual(manifest["source_layer"], "FMZK_WIEN_20260112")
			with self.assertRaises(FileExistsError):
				with patch("scripts.extract_fmzk.shutil.which", return_value="/usr/bin/ogr2ogr"):
					extract(source, output, parse_bbox(DEFAULT_BBOX))


if __name__ == "__main__":
	unittest.main()
