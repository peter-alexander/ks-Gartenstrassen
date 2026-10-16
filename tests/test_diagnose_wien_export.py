"""Offline-Tests zur schreibgeschützten WGS84-Export-Diagnose."""
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from shapely import from_wkb
from shapely.geometry import box

from scripts.diagnose_wien_export import diagnose
from scripts.wienwide_qa_gpkg import gpkg_blob
from scripts.wienwide_result_export import WGS84


class DiagnoseWienExportTests(unittest.TestCase):
	def setUp(self):
		self.temp=TemporaryDirectory()
		self.addCleanup(self.temp.cleanup)
		self.root=Path(self.temp.name)
		self.gpkg=self.root/"quelle.gpkg"
		with sqlite3.connect(self.gpkg) as db:
			db.execute("""CREATE TABLE gip_abschnitte(
				fid INTEGER PRIMARY KEY,
				gip_id TEXT NOT NULL,
				geom BLOB NOT NULL,
				flaeche_m2 REAL NOT NULL)""")
			for fid,gid,shape in (
				(1,"10023323",box(8000,350000,8050,350100)),
				(2,"10023323",box(8050,350000,8100,350100)),
				(3,"10023274",box(8200,350000,8210,350100)),
			):
				db.execute("INSERT INTO gip_abschnitte VALUES(?,?,?,?)",
					(fid,gid,gpkg_blob(shape),shape.area))

	def test_export_diagnostic_records_originals_and_roundtrip_without_writes(self):
		start=sha256(self.gpkg.read_bytes()).hexdigest()
		lon,lat=WGS84(8050,350050)
		zipfile=self.root/"diagnose.zip"
		report=diagnose(self.gpkg,zipfile,["10023323","10023274"],
			lon=lon,lat=lat,radius_m=3)
		self.assertEqual(sha256(self.gpkg.read_bytes()).hexdigest(),start)
		self.assertEqual(report["gip_ids"],["10023323","10023274"])
		with ZipFile(zipfile) as archive:
			names=set(archive.namelist())
			self.assertIn("diagnose.json",names)
			self.assertIn(
				"gip_10023323/00_original_metric_union.wkb",names)
			self.assertIn("gip_10023323/01_wgs84_unveraendert.wkb",names)
			self.assertIn(
				"gip_10023323/06_rueck_repariert_polygonal.wkb",names)
			self.assertIn("gip_10023323/08_zusaetzliche_metric.wkb",names)
			self.assertIn("gip_10023323/09_fehlende_metric.wkb",names)
			self.assertIn(
				"gip_10023323/10_fehlstelle_original_31256.wkb",names)
			self.assertIn("gip_10023323/fragment_00000.wkb",names)
			self.assertIn("gip_10023323/fragment_00001.wkb",names)
			original=from_wkb(archive.read(
				"gip_10023323/00_original_metric_union.wkb"))
			self.assertTrue(original.is_valid)
			self.assertAlmostEqual(original.area,10000)
			wkb_report=json.loads(archive.read("diagnose.json"))
			self.assertEqual(wkb_report["ausgaben"]["10023323"]
				["anzahl_fragmente"],2)
			self.assertAlmostEqual(wkb_report["ausgaben"]["10023323"]
				["messwerte"]["grenzverschiebung_hausdorff_m"],0,
				delta=.01)
			self.assertEqual(len(wkb_report["ausgaben"]["10023323"]
				["fragmente"]),2)
		with self.assertRaises(FileExistsError):
			diagnose(self.gpkg,zipfile,["10023323"])

	def test_missing_gip_does_not_create_zip(self):
		out=self.root/"nichts.zip"
		with self.assertRaisesRegex(ValueError,
			"keine Teilflächen"):
			diagnose(self.gpkg,out,["99999999"])
		self.assertFalse(out.exists())

	def test_duplicate_gip_list_is_rejected_without_output(self):
		out=self.root/"duplikat.zip"
		with self.assertRaisesRegex(ValueError,
			"eindeutige GIP-ID"):
			diagnose(self.gpkg,out,["10023323","10023323"])
		self.assertFalse(out.exists())

	def test_lon_lat_must_be_paired(self):
		out=self.root/"ungültig.zip"
		with self.assertRaisesRegex(ValueError,"nur gemeinsam"):
			diagnose(self.gpkg,out,["10023323"],lon=16.2)
		self.assertFalse(out.exists())

	def test_corrupted_source_area_is_not_silently_extracted(self):
		with sqlite3.connect(self.gpkg) as db:
			db.execute("UPDATE gip_abschnitte SET flaeche_m2=1 "
				"WHERE fid=1")
		out=self.root/"fehler.zip"
		with self.assertRaisesRegex(ValueError,
			"stimmen nicht überein"):
			diagnose(self.gpkg,out,["10023323"])
		self.assertFalse(out.exists())


if __name__=="__main__":
	unittest.main()
