"""Regressionstests für die optimierte SIS-V2-Wien-Messroutine."""
import sqlite3
import unittest

from shapely.geometry import box
from shapely.wkb import dumps

from scripts.sis_v2_measure import _duration, _vegetation_mask
from scripts.sis_wien_source import mask


class SISWienMeasurementPerformanceTests(unittest.TestCase):
	def setUp(self):
		self.db = sqlite3.connect(":memory:")
		self.addCleanup(self.db.close)
		self.db.execute("CREATE TABLE features (id INTEGER PRIMARY KEY, belag TEXT, geom BLOB)")
		self.db.execute(
			"CREATE VIRTUAL TABLE feature_index USING rtree(id,minx,maxx,miny,maxy)"
		)
		self.add("WI", box(0, 0, 10, 10))
		self.add("BL", box(5, 5, 15, 15))
		self.add("GA", box(6, 0, 12, 10))
		self.add("ST", box(30, 0, 40, 10))
		self.add("GA", box(100, 100, 110, 110))

	def add(self, belag, geometry):
		cur = self.db.execute(
			"INSERT INTO features(belag,geom) VALUES (?,?)",
			(belag, dumps(geometry)),
		)
		x0, y0, x1, y1 = geometry.bounds
		self.db.execute(
			"INSERT INTO feature_index VALUES (?,?,?,?,?)",
			(cur.lastrowid, x0, x1, y0, y1),
		)

	def test_matches_original_two_mask_semantics_with_overlaps(self):
		# Die bisherige Regel: Vereinigung aller grünen Flächen,
		# abzüglich der Vereinigung ALLER nicht grünen Flächen.
		core = box(-5, -5, 25, 25)
		green = mask(self.db, core, {"BL", "ST", "WI"})
		non_green = mask(self.db, core, {"GA"})
		reference = green.difference(non_green)
		result = _vegetation_mask(self.db, core, city=True)
		self.assertIsNotNone(result)
		self.assertAlmostEqual(result.area, reference.area, delta=1e-9)
		self.assertLess(result.symmetric_difference(reference).area, 1e-9)
		self.assertTrue(result.is_valid)

	def test_only_one_spatial_select_and_no_full_table_scan(self):
		queries = []
		self.db.set_trace_callback(queries.append)
		try:
			result = _vegetation_mask(self.db, box(0, 0, 20, 20), city=True)
		finally:
			self.db.set_trace_callback(None)
		self.assertGreater(result.area, 0)
		reads = [q for q in queries if "FROM features f" in q]
		self.assertEqual(len(reads), 1, queries)
		self.assertIn("JOIN feature_index", reads[0])
		self.assertFalse(any("DISTINCT belag" in q for q in queries), queries)

	def test_vegetation_only_and_none(self):
		self.assertAlmostEqual(
			_vegetation_mask(self.db, box(30, 0, 40, 10), city=True).area, 100.
		)
		self.assertIsNone(
			_vegetation_mask(self.db, box(100, 100, 110, 110), city=True)
		)
		self.assertIsNone(
			_vegetation_mask(self.db, box(200, 200, 210, 210), city=True)
		)

	def test_duration_format(self):
		self.assertEqual(_duration(0), "00:00:00")
		self.assertEqual(_duration(3723.5), "01:02:03")
		self.assertEqual(_duration(-10), "00:00:00")


if __name__ == "__main__":
	unittest.main()
