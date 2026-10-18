import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest

from shapely import to_wkb
from shapely.geometry import LineString, Polygon, box

from scripts.analyze_gpkg import analyze, decode_gpkg_geometry
from scripts.extract_fmzk import DEFAULT_BBOX, parse_bbox, projected_clip


def blob_for_geometry(geometry, *, envelope=False):
	# GeoPackageBinary V0, little endian, EPSG:31256 und WKB.
	flags = 3 if envelope else 1
	header = b"GP" + bytes([0, flags]) + struct.pack("<i", 31256)
	if envelope:
		header += struct.pack("<dddd", *geometry.bounds)
	return header + to_wkb(geometry)


def create_test_source(root, geometries):
	path = root / "fmzk_test.gpkg"
	with sqlite3.connect(path) as conn:
		conn.executescript("""
			CREATE TABLE gpkg_contents (table_name TEXT, srs_id INTEGER);
			CREATE TABLE gpkg_geometry_columns (table_name TEXT, column_name TEXT, srs_id INTEGER);
			INSERT INTO gpkg_contents VALUES ('fmzk', 31256);
			INSERT INTO gpkg_geometry_columns VALUES ('fmzk', 'geom', 31256);
			CREATE TABLE fmzk (
				id INTEGER PRIMARY KEY, geom BLOB,
				F_KLASSE INTEGER, F_KLASSE_TEXT TEXT, FMZK_ID INTEGER
			);
		""")
		for index, (geom, code, label) in enumerate(geometries, 1):
			conn.execute(
				"INSERT INTO fmzk (id, geom, F_KLASSE, F_KLASSE_TEXT, FMZK_ID) VALUES (?, ?, ?, ?, ?)",
				(index, blob_for_geometry(geom, envelope=index % 2 == 0), code, label, index),
			)
	path.with_suffix(".json").write_text(json.dumps({
		"output_layer": "fmzk",
		"output_srs": "EPSG:31256",
		"bbox_lon_lat": list(parse_bbox(DEFAULT_BBOX)),
		"feature_count": len(geometries),
	}))
	return path


class AnalyzeGpkgTest(unittest.TestCase):
	def setUp(self):
		p = projected_clip(parse_bbox(DEFAULT_BBOX)).centroid
		self.x, self.y = p.x, p.y

	def test_decode_without_and_with_envelope(self):
		g = box(self.x, self.y, self.x + 10, self.y + 10)
		for envelope in (False, True):
			with self.subTest(envelope=envelope):
				self.assertTrue(decode_gpkg_geometry(blob_for_geometry(g, envelope=envelope), 1).equals(g))
		with self.assertRaisesRegex(ValueError, "Header"):
			decode_gpkg_geometry(b"garbage", 4)
		with self.assertRaisesRegex(ValueError, "Geometrie-SRS"):
			decode_gpkg_geometry(b"GP" + bytes([0, 1]) + struct.pack("<i", 3857) + to_wkb(g), 4)

	def test_union_deduplicates_areas_and_reports_cross_class_overlap(self):
		a = box(self.x - 10, self.y - 10, self.x, self.y)
		b = box(self.x - 5, self.y - 10, self.x + 5, self.y)
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			source = create_test_source(root, [(a, 21, "Fahrbahn"), (a, 21, "Fahrbahn"), (b, 58, "Grünfläche")])
			report = analyze(source, root / "out")
			self.assertEqual(report["feature_count"], 3)
			self.assertEqual(len(report["categories"]), 2)
			self.assertEqual(report["geometry_repairs"], [])
			self.assertAlmostEqual(report["categories"][0]["flaeche_m2"], 100, delta=0.0001)
			self.assertEqual(report["categories"][0]["objekte"], 2)
			self.assertAlmostEqual(report["categories"][1]["flaeche_m2"], 100, delta=0.0001)
			self.assertAlmostEqual(report["union_area_m2"], 150, delta=0.0001)
			self.assertAlmostEqual(report["overlap_across_classes_m2"], 50, delta=0.0001)
			self.assertTrue((root / "out" / "fmzk_klassen.csv").is_file())
			self.assertTrue((root / "out" / "fmzk_report.json").is_file())

	def test_make_valid_is_logged_and_bad_nonpolygon_rejected(self):
		bowtie = Polygon([
			(self.x - 3, self.y - 3), (self.x + 3, self.y + 3),
			(self.x - 3, self.y + 3), (self.x + 3, self.y - 3),
		])
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			source = create_test_source(root, [(bowtie, 21, "Fahrbahn")])
			report = analyze(source, root / "out")
			self.assertEqual(len(report["geometry_repairs"]), 1)
			self.assertEqual(report["geometry_repairs"][0]["id"], 1)
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			source = create_test_source(root, [(LineString([(self.x, self.y), (self.x + 1, self.y + 1)]), 21, "Fahrbahn")])
			with self.assertRaisesRegex(ValueError, "erwartet Polygon/MultiPolygon"):
				analyze(source, root / "out")

	def test_off_bbox_rejected_and_missing_metadata(self):
		geom = box(self.x + 3000, self.y, self.x + 3010, self.y + 10)
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			source = create_test_source(root, [(geom, 21, "Fahrbahn")])
			with self.assertRaisesRegex(ValueError, "außerhalb der Extraktions-BBOX"):
				analyze(source, root / "out")
			source.with_suffix(".json").unlink()
			with self.assertRaises(FileNotFoundError):
				analyze(source, root / "out")


if __name__ == "__main__":
	unittest.main()
