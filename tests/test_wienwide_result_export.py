"""Regression tests for complete-GIP publication filtering (not tile filtering)."""
import csv
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from shapely.geometry import box, Polygon
from shapely.affinity import translate
from shapely.ops import transform

from scripts.wienwide_qa_gpkg import gpkg_blob
from scripts.wienwide_gip_greening import CSV_COLUMNS
from scripts.wienwide_result_export import (
	WGS84,_verified_wgs84,export,
)


class WienwideResultExportTests(unittest.TestCase):
	def setUp(self):
		self.folder = TemporaryDirectory()
		self.addCleanup(self.folder.cleanup)
		self.root = Path(self.folder.name)
		self.csv_path = self.root / "complete.csv"
		self.gpkg_path = self.root / "complete.gpkg"
		self.rows = [
			{
				"gip_id": "A", "strassenname": "Teststraße",
				"fow": 3, "abschnitt_flaeche_m2": 120.0,
				"boden_m2": 15, "boden_pct": 12.5,
				"boden_58_m2": 0, "boden_69_m2": 15,
				"boden_klassen_ueberlagerung_m2": 0,
				"grm_kronen_m2": 30, "grm_kronen_pct": 25,
				"kachelteile": 2,
			},
			{
				"gip_id": "B", "strassenname": "Kleinstfläche",
				"fow": 3, "abschnitt_flaeche_m2": 40.0,
				"boden_m2": 0, "boden_pct": 0,
				"boden_58_m2": 0, "boden_69_m2": 0,
				"boden_klassen_ueberlagerung_m2": 0,
				"grm_kronen_m2": None, "grm_kronen_pct": None,
				"kachelteile": 1,
			},
		]
		with self.csv_path.open("w", encoding="utf-8", newline="") as target:
			writer = csv.DictWriter(target, fieldnames=CSV_COLUMNS)
			writer.writeheader()
			writer.writerows(self.rows)
		with sqlite3.connect(self.gpkg_path) as db:
			db.execute("CREATE TABLE qa_provenienz (key TEXT PRIMARY KEY, value TEXT)")
			db.execute("INSERT INTO qa_provenienz VALUES (?,?)", (
				"gip_begruenung_v1",
				json.dumps({
					"gip_ids": 2,
					"ausgewertete_abschnittsflaeche_m2": 160.,
					"strassenraum_m2": 200.,
					"nicht_in_abschnittsquoten_m2": 40.,
				}),
			))
			db.execute("""CREATE TABLE gip_abschnitte (
				fid INTEGER PRIMARY KEY,
				gip_id TEXT NOT NULL,
				geom BLOB NOT NULL,
				flaeche_m2 REAL NOT NULL,
				gip_gesamt_m2 REAL NOT NULL)""")
			features = (
				("A", box(1000, 342000, 1012, 342005), 120.),
				("A", box(1012, 342000, 1024, 342005), 120.),
				("B", box(1030, 342000, 1038, 342005), 40.),
			)
			for gid, geom, total in features:
				db.execute("""INSERT INTO gip_abschnitte
					(gip_id, geom, flaeche_m2, gip_gesamt_m2)
					VALUES (?,?,?,?)""",
					(gid, gpkg_blob(geom), geom.area, total))

	def _invalid_wgs84_boundary_repetition(self):
		# Reale Projektion einer metrisch gültigen Fläche; eine
		# doppelt durchlaufene Grenzkante erzeugt einen
		# topologischen WGS84-Fehler ohne zusätzliche Flächen.
		metric=box(8000,350000,8100,350100)
		normal=transform(WGS84,metric)
		points=list(normal.exterior.coords)
		start,second=points[:2]
		middle=((start[0]+second[0])/2,
			(start[1]+second[1])/2)
		invalid=Polygon(points+[middle,start])
		self.assertFalse(invalid.is_valid)
		return metric,normal,invalid

	def test_valid_wgs84_remains_unchanged_without_repair(self):
		metric,valid,_invalid=self._invalid_wgs84_boundary_repetition()
		audit=[]
		result=_verified_wgs84(metric,valid,"10023274",audit)
		self.assertIs(result,valid)
		self.assertEqual(audit,[])

	def test_invalid_wgs84_small_edge_artifact_only_repairs_output(self):
		metric,_valid,invalid=self._invalid_wgs84_boundary_repetition()
		audit=[]
		result=_verified_wgs84(metric,invalid,"10023274",audit)
		self.assertTrue(result.is_valid)
		self.assertFalse(result.is_empty)
		self.assertEqual(len(audit),1)
		self.assertEqual(audit[0]["gip_id"],"10023274")
		self.assertLess(audit[0]["grenzverschiebung_m"],.01)
		self.assertLess(audit[0]["fehlend_m2"],
			audit[0]["differenztoleranz_m2"])
		self.assertLess(audit[0]["zusaetzlich_m2"],
			audit[0]["differenztoleranz_m2"])
		self.assertEqual(metric.area,10000)

	def test_invalid_wgs84_rejects_shifted_repair(self):
		metric,valid,invalid=self._invalid_wgs84_boundary_repetition()
		shifted=translate(valid,xoff=.0001)  # mehrere Meter
		audit=[]
		with patch("scripts.wienwide_result_export.make_valid",
			return_value=shifted):
			with self.assertRaisesRegex(ValueError,
				"Reparatur nicht metrisch flächentreu"):
				_verified_wgs84(metric,invalid,"10023274",audit)
		self.assertEqual(audit,[])

	def test_invalid_wgs84_rejects_lost_area(self):
		metric,valid,invalid=self._invalid_wgs84_boundary_repetition()
		removed=box(valid.bounds[0],valid.bounds[1],
			(valid.bounds[0]+valid.bounds[2])/2,valid.bounds[3])
		audit=[]
		with patch("scripts.wienwide_result_export.make_valid",
			return_value=removed):
			with self.assertRaisesRegex(ValueError,
				"Reparatur nicht metrisch flächentreu"):
				_verified_wgs84(metric,invalid,"10023274",audit)
		self.assertEqual(audit,[])

	def test_one_global_section_kept_even_when_both_tiles_below_threshold(self):
		out = self.root / "published"
		result = export(self.csv_path, self.gpkg_path, out)
		self.assertEqual(result["output_gip_ids"], 1)
		self.assertEqual(result["omitted_gip_ids"], 1)
		self.assertAlmostEqual(result["omitted_assigned_m2"], 40.)
		doc = json.loads((out / "gip_abschnitte.geojson").read_text(encoding="utf-8"))
		self.assertEqual(len(doc["features"]), 1)
		feature = doc["features"][0]
		self.assertEqual(feature["properties"]["gip_id"], "A")
		self.assertEqual(feature["properties"]["kachelteile"], 2)
		self.assertAlmostEqual(feature["properties"]["abschnitt_flaeche_m2"], 120.)
		with (out / "gip_abschnitte.csv").open(encoding="utf-8", newline="") as src:
			self.assertEqual([r["gip_id"] for r in csv.DictReader(src)], ["A"])
		self.assertTrue(self.csv_path.exists())
		self.assertTrue(self.gpkg_path.exists())

	def test_null_canopy_is_preserved_when_zero_threshold(self):
		out = self.root / "all"
		result = export(self.csv_path, self.gpkg_path, out, min_area_m2=0)
		self.assertEqual(result["output_gip_ids"], 2)
		doc = json.loads((out / "gip_abschnitte.geojson").read_text(encoding="utf-8"))
		props = {f["properties"]["gip_id"]: f["properties"] for f in doc["features"]}
		self.assertIsNone(props["B"]["grm_kronen_pct"])
		self.assertEqual(props["B"]["boden_pct"], 0)

	def test_inconsistent_fragment_area_aborts_without_partial_output(self):
		with sqlite3.connect(self.gpkg_path) as db:
			db.execute("UPDATE gip_abschnitte SET gip_gesamt_m2=121 WHERE gip_id='A'")
		out = self.root / "bad"
		with self.assertRaisesRegex(ValueError, "Flächen-/Fragmentbilanz"):
			export(self.csv_path, self.gpkg_path, out)
		self.assertFalse(out.exists())
		self.assertFalse((self.root / "bad.tmp").exists())

	def test_invalid_csv_percent_rejected(self):
		self.rows[0]["boden_pct"] = 99
		with self.csv_path.open("w", encoding="utf-8", newline="") as target:
			writer = csv.DictWriter(target, fieldnames=CSV_COLUMNS)
			writer.writeheader()
			writer.writerows(self.rows)
		with self.assertRaisesRegex(ValueError, "boden_m2"):
			export(self.csv_path, self.gpkg_path, self.root / "bad_percent")


if __name__ == "__main__":
	unittest.main()
