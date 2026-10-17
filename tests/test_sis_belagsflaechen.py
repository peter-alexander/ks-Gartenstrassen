"""Offline-Tests für den eigenständigen SIS-Testkachel-Provider."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from pyproj import Transformer
from shapely.geometry import box, mapping
from shapely.ops import transform
from shapely.wkb import loads

from scripts.sis_belagsflaechen import build, read_surfaces


class SISBelagsflaechenTests(unittest.TestCase):
	def setUp(self):
		self.temp = tempfile.TemporaryDirectory()
		self.addCleanup(self.temp.cleanup)
		self.base = Path(self.temp.name)
		to_wgs = Transformer.from_crs("EPSG:31256", "EPSG:4326",
			always_xy=True).transform
		x, y = Transformer.from_crs("EPSG:4326", "EPSG:31256",
			always_xy=True).transform(16.36, 48.22)
		self.polys = [box(x,y,x+20,y+20), box(x+20,y,x+40,y+20)]
		self.doc = {"type": "FeatureCollection", "features": [
			{"type": "Feature", "properties": {"TYPE": kind, "BELAG": belag, "BELAG_TXT": belag_txt},
				"geometry": mapping(transform(to_wgs, poly))}
			for kind, belag, belag_txt, poly in zip(("GG", "EE"), ("GA", "WI"),
			("Gussasphalt Gehsteig", "Wiese"), self.polys)
		]}
		self.source = self.base/"source.json"
		self.source.write_text(json.dumps(self.doc), encoding="utf-8")

	def test_preserves_all_types_and_area_union(self):
		report = build(self.source, self.base/"out")
		self.assertEqual(report["features"], 2)
		self.assertEqual(set(report["type_klassen"]), {"GG","EE"})
		self.assertEqual(set(report["belag_klassen"]), {"GA","WI"})
		self.assertAlmostEqual(report["vereinigte_strassenbelagsflaeche_m2"], 800, delta=.05)
		self.assertAlmostEqual(report["ueberlagerungsflaeche_m2"], 0, delta=.05)
		with sqlite3.connect(self.base/"out"/"sis.sqlite") as db:
			street = loads(db.execute("SELECT geom FROM street").fetchone()[0])
			self.assertAlmostEqual(street.area, 800, delta=.05)
			rows = db.execute("SELECT type,belag FROM surfaces ORDER BY id").fetchall()
			self.assertEqual(rows, [("GG","GA"), ("EE","WI")])
			bbox = db.execute("SELECT minx,maxx,miny,maxy FROM surface_index WHERE id=0").fetchone()
			self.assertAlmostEqual(bbox[0], self.polys[0].bounds[0], delta=.2)
			self.assertAlmostEqual(bbox[1], self.polys[0].bounds[2], delta=.2)
			self.assertAlmostEqual(bbox[2], self.polys[0].bounds[1], delta=.2)
			self.assertAlmostEqual(bbox[3], self.polys[0].bounds[3], delta=.2)
		self.assertEqual((self.base/"out"/"SISBELAGOGD.json").read_bytes(),
			self.source.read_bytes())
		with self.assertRaises(FileExistsError):
			build(self.source, self.base/"out")

	def test_overlap_fails_without_writing(self):
		doc = json.loads(self.source.read_text(encoding="utf-8"))
		to_wgs = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform
		doc["features"][1]["geometry"] = mapping(transform(to_wgs,
			self.polys[1].translate(-10, 0) if hasattr(self.polys[1], "translate") else box(
				self.polys[1].bounds[0]-10, self.polys[1].bounds[1],
				self.polys[1].bounds[2]-10, self.polys[1].bounds[3])))
		self.source.write_text(json.dumps(doc), encoding="utf-8")
		with self.assertRaisesRegex(ValueError, "überlappen"):
			build(self.source, self.base/"out")
		self.assertFalse((self.base/"out").exists())

	def test_invalid_missing_type_rejected_without_output(self):
		doc = json.loads(self.source.read_text(encoding="utf-8"))
		del doc["features"][0]["properties"]["TYPE"]
		self.source.write_text(json.dumps(doc), encoding="utf-8")
		with self.assertRaisesRegex(ValueError, "TYPE"):
			build(self.source, self.base/"out")
		self.assertFalse((self.base/"out").exists())

	def test_bad_crs_rejected(self):
		doc = json.loads(self.source.read_text(encoding="utf-8"))
		doc["crs"] = {"type": "name", "properties": {"name": "EPSG:3857"}}
		self.source.write_text(json.dumps(doc), encoding="utf-8")
		with self.assertRaisesRegex(ValueError, "CRS"):
			read_surfaces(self.source)


if __name__ == "__main__":
	unittest.main()
