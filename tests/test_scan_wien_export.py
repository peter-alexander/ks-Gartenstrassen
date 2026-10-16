"""Regressionen für Wienweite schreibgeschützte WGS84-Exportvorprüfung."""
import csv
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from shapely.geometry import box

from scripts.scan_wien_export import scan
from scripts.wienwide_gip_greening import CSV_COLUMNS
from scripts.wienwide_qa_gpkg import gpkg_blob


class WienExportPreflightTests(unittest.TestCase):
	def setUp(self):
		self.temp=TemporaryDirectory()
		self.addCleanup(self.temp.cleanup)
		self.root=Path(self.temp.name)
		self.csv=self.root/"messung.csv"
		self.gpkg=self.root/"messung.gpkg"
		records=[
			{"gip_id":"A","strassenname":"A-Straße","fow":3,
				"abschnitt_flaeche_m2":120.,"boden_m2":15.,
				"boden_pct":12.5,"boden_58_m2":15.,"boden_69_m2":0,
				"boden_klassen_ueberlagerung_m2":0,
				"grm_kronen_m2":30,"grm_kronen_pct":25.,
				"kachelteile":2},
			{"gip_id":"B","strassenname":"B-Straße","fow":3,
				"abschnitt_flaeche_m2":40.,"boden_m2":0.,
				"boden_pct":0.,"boden_58_m2":0.,"boden_69_m2":0.,
				"boden_klassen_ueberlagerung_m2":0,
				"grm_kronen_m2":0.,"grm_kronen_pct":0.,
				"kachelteile":1},
			{"gip_id":"C","strassenname":"C-Straße","fow":3,
				"abschnitt_flaeche_m2":150.,"boden_m2":15.,
				"boden_pct":10.,"boden_58_m2":15.,"boden_69_m2":0,
				"boden_klassen_ueberlagerung_m2":0,
				"grm_kronen_m2":60,"grm_kronen_pct":40.,
				"kachelteile":1},
		]
		with self.csv.open("w",newline="",encoding="utf-8") as target:
			writer=csv.DictWriter(target,fieldnames=CSV_COLUMNS)
			writer.writeheader()
			writer.writerows(records)
		with sqlite3.connect(self.gpkg) as db:
			db.execute("CREATE TABLE qa_provenienz(key TEXT PRIMARY KEY,value TEXT)")
			db.execute("INSERT INTO qa_provenienz VALUES(?,?)",
				("gip_begruenung_v1",json.dumps({
					"gip_ids":3,
					"ausgewertete_abschnittsflaeche_m2":310.,
					"strassenraum_m2":350.,
					"nicht_in_abschnittsquoten_m2":40.,
				})))
			db.execute("""CREATE TABLE gip_abschnitte(
				fid INTEGER PRIMARY KEY,gip_id TEXT NOT NULL,
				geom BLOB NOT NULL,flaeche_m2 REAL NOT NULL,
				gip_gesamt_m2 REAL NOT NULL)""")
			parts=[
				(1,"A",box(8000,350000,8012,350005),120.),
				(2,"A",box(8012,350000,8024,350005),120.),
				(3,"B",box(8030,350000,8038,350005),40.),
				(4,"C",box(8040,350000,8070,350005),150.),
			]
			for fid,gid,geom,total in parts:
				db.execute("INSERT INTO gip_abschnitte VALUES(?,?,?,?,?)",
					(fid,gid,gpkg_blob(geom),geom.area,total))

	def test_full_preflight_passes_and_does_not_create_empty_zip(self):
		old_csv=sha256(self.csv.read_bytes()).hexdigest()
		old_gpkg=sha256(self.gpkg.read_bytes()).hexdigest()
		out=self.root/"report.json"
		zip_path=self.root/"evidence.zip"
		result=scan(self.csv,self.gpkg,out,zip_path)
		self.assertEqual(result["gip_ids_gesamt"],3)
		self.assertEqual(result["gip_ids_im_export"],2)
		self.assertEqual(result["gip_ids_geprueft"],2)
		self.assertEqual(result["gip_ids_fehlgeschlagen"],0)
		self.assertEqual(result["gip_ids_bestanden"],2)
		self.assertEqual(result["fehler"],[])
		self.assertFalse(zip_path.exists())
		self.assertEqual(sha256(self.csv.read_bytes()).hexdigest(),old_csv)
		self.assertEqual(sha256(self.gpkg.read_bytes()).hexdigest(),old_gpkg)
		self.assertEqual(json.loads(out.read_text())[
			"gip_ids_geprueft"],2)
		with self.assertRaises(FileExistsError):
			scan(self.csv,self.gpkg,out,zip_path)

	def test_scans_past_first_failure_and_zips_all_detected_failures(self):
		out=self.root/"report.json"
		zip_path=self.root/"evidence.zip"
		actual=__import__("scripts.scan_wien_export",fromlist=["_inspect_group"])
		original=actual._inspect_group
		def inject_one_failure(gid,fragments,area):
			if gid=="A":
				raise ValueError("metrische Grenzverschiebung 6.070347 m")
			return original(gid,fragments,area)
		with patch("scripts.scan_wien_export._inspect_group",
			side_effect=inject_one_failure):
			result=scan(self.csv,self.gpkg,out,zip_path)
		self.assertEqual(result["gip_ids_geprueft"],2)
		self.assertEqual(result["gip_ids_fehlgeschlagen"],1)
		self.assertEqual(result["gip_ids_bestanden"],1)
		self.assertEqual(result["fehler"][0]["gip_id"],"A")
		self.assertIn("6.070347",result["fehler"][0]["fehler"])
		self.assertEqual(result["diagnosezip_erfasst"],1)
		self.assertEqual(result["diagnosezip_nicht_erfasst"],0)
		with ZipFile(zip_path) as archive:
			names=set(archive.namelist())
			self.assertIn("gip_A/00_original_metric_union.wkb",names)
			self.assertIn("gip_A/fragment_00000.wkb",names)
			self.assertIn("gip_A/fragment_00001.wkb",names)
			self.assertIn("diagnose.json",names)
			self.assertEqual(json.loads(archive.read("diagnose.json"))[
				"ids"],["A"])

	def test_zip_cap_does_not_hide_additional_errors(self):
		out=self.root/"report.json"
		zip_path=self.root/"evidence.zip"
		with patch("scripts.scan_wien_export._inspect_group",
			side_effect=ValueError("topologischer Fehler")):
			result=scan(self.csv,self.gpkg,out,zip_path,max_diagnostics=1)
		self.assertEqual(result["gip_ids_geprueft"],2)
		self.assertEqual(result["gip_ids_fehlgeschlagen"],2)
		self.assertEqual(len(result["fehler"]),2)
		self.assertEqual(result["diagnosezip_erfasst"],1)
		self.assertEqual(result["diagnosezip_nicht_erfasst"],1)

	def test_bad_csv_prevents_any_scan_output(self):
		self.csv.write_text("unknown\n",encoding="utf-8")
		out=self.root/"report.json"
		zip_path=self.root/"evidence.zip"
		with self.assertRaisesRegex(ValueError,"CSV-Schema"):
			scan(self.csv,self.gpkg,out,zip_path)
		self.assertFalse(out.exists())
		self.assertFalse(zip_path.exists())


if __name__=="__main__":
	unittest.main()
