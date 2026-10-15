"""Wienweite FMZK-/GRM-Abschnittskennzahlen ohne Netzwerk oder echte Bezirksdaten."""
import csv
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from pyproj import Transformer
from shapely.geometry import box,mapping
from shapely.ops import transform

from scripts.wienwide_grid import build_manifest,read_manifest,write_manifest,checksum
from scripts.wienwide_street import save_street_tile
from scripts.wienwide_partition import connect_results,write_tile
from scripts.wienwide_qa_gpkg import export as qa_export
from scripts.wienwide_gip_greening import run, _compute


class WienwideGreeningTests(unittest.TestCase):
	def setUp(self):
		self.temporary=tempfile.TemporaryDirectory()
		self.addCleanup(self.temporary.cleanup)
		self.root=Path(self.temporary.name)
		t=Transformer.from_crs("EPSG:4326","EPSG:31256",always_xy=True)
		to_geo=Transformer.from_crs("EPSG:31256","EPSG:4326",
			always_xy=True).transform
		x,y=t.transform(16.365,48.225)
		x=math.floor(x/250)*250+80
		y=math.floor(y/250)*250+80
		aoi=box(x,y,x+40,y+30)
		geo=self.root/"aoi.geojson"
		geo.write_text(json.dumps(mapping(transform(to_geo,aoi))))
		self.manifest=self.root/"raster.json"
		write_manifest(self.manifest,build_manifest(geo,size=250,halo=75))
		m,aoi=read_manifest(self.manifest)
		self.assertEqual(len(m["tiles"]),1)
		self.tile=m["tiles"][0]
		self.aoi=aoi
		self.x0,self.y0,self.x1,self.y1=aoi.bounds
		d=(self.x1-self.x0)/3
		self.first=aoi.intersection(box(self.x0,self.y0,
			self.x0+d,self.y1))
		self.second=aoi.intersection(box(self.x0+d,self.y0,
			self.x0+2*d,self.y1))
		self.rest=aoi.difference(self.first.union(self.second))
		self.green_58=aoi.intersection(box(self.x0,self.y0,
			self.x0+d/2,self.y0+15))
		self.green_69=aoi.intersection(box(self.x0+d/4,self.y0,
			self.x0+2*d+1,self.y0+10))
		self.crown=aoi.intersection(box(self.x0,self.y0,
			self.x0+d*1.5,self.y0+6))
		self.fmzk_root=self.root/"inputs"
		fmzk_dir=self.fmzk_root/self.tile["id"]
		fmzk_dir.mkdir(parents=True)
		self.fmzk=fmzk_dir/"fmzk.gpkg"
		self.fmzk.write_bytes(b"local unmodified fmzk test source")
		self.street=self.root/"strassenraum"
		save_street_tile(self.street/self.tile["id"]/"street.sqlite",
			aoi,{"schema_version":"1","crs":"EPSG:31256",
				"tile_id":self.tile["id"],
				"strassenraum_regel_version":"fmzk-core-21-23-24-25-33-39-nfl-95-65-v2",
				"fmzk_sha256":checksum(self.fmzk)})
		self.gip=self.root/"gip.sqlite"
		with sqlite3.connect(self.gip) as db:
			db.executescript("""CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
				CREATE TABLE axes(gip TEXT PRIMARY KEY,name TEXT,fow INTEGER,
					node_from TEXT,node_to TEXT);""")
			db.execute("INSERT INTO meta VALUES (?,?)",
				("manifest_sha256",json.dumps(checksum(self.manifest))))
			db.executemany("INSERT INTO axes VALUES (?,?,?,?,?)",[
				("11","Erste Straße",3,"a","b"),
				("22","Zweite Straße",3,"c","d"),
			])
		self.partition=self.root/"aufteilung.sqlite"
		with connect_results(self.partition,create=True) as db:
			db.executemany("INSERT INTO config VALUES (?,?)",[
				("manifest_sha256",checksum(self.manifest)),
				("gip_sha256",checksum(self.gip)),
				("schema_version","1")
			])
			stats={"strassenraum_m2":aoi.area,
				"zugeordnet_m2":self.first.area+self.second.area,
				"ungeklaert_m2":self.rest.area,
				"fehlend_m2":0,"overlap_m2":0,"ausserhalb_m2":0,
				"toleranz_m2":.05,"sites":10,"knoten":0}
			write_tile(db,self.tile["id"],
				checksum(self.street/self.tile["id"]/"street.sqlite"),
				{"11":self.first,"22":self.second},
				{"nicht_zugeordnet":self.rest},stats,.04)
		self.qa=self.root/"qa.gpkg"
		qa_export(self.manifest,self.gip,self.street,self.partition,self.qa)
		self.features=[
			(1,58,"Gruen 58",self.green_58),
			(2,69,"Gruen 69",self.green_69),
			(3,21,"Fahrbahn",aoi),
		]
		self.fmzk_return=(self.features,{"bbox_lon_lat":[16.36,48.21,16.37,48.23]},
			aoi.buffer(50),[])

	def run_it(self,path,grm=None):
		with patch("scripts.wienwide_gip_greening.load_polygons",
			return_value=self.fmzk_return):
			return run(self.manifest,self.gip,self.street,self.fmzk_root,
				self.partition,self.qa,self.root/path,grm_root=grm)

	def test_ground_union_separate_classes_excludes_unassigned(self):
		out=self.run_it("boden")
		self.assertEqual(out["gip_ids"],2)
		self.assertAlmostEqual(out["ausgewertete_abschnittsflaeche_m2"],
			self.first.area+self.second.area,delta=.001)
		self.assertEqual(out["grm_kronen_m2"],None)
		expected=(self.green_58.union(self.green_69)).intersection(
			self.first.union(self.second)).area
		self.assertAlmostEqual(out["boden_m2"],expected,delta=.001)
		self.assertAlmostEqual(out["nicht_in_abschnittsquoten_m2"],
			self.rest.area,delta=.001)
		path=self.root/"boden"
		with (path/"gip_abschnitte_begruenung.csv").open(
			encoding="utf-8",newline="") as f:
			rows=list(csv.DictReader(f))
		self.assertEqual(len(rows),2)
		self.assertEqual({r["gip_id"] for r in rows},{"11","22"})
		self.assertEqual(rows[0]["grm_kronen_pct"],"")
		with sqlite3.connect(path/"gip_abschnitte_begruenung.gpkg") as db:
			raw=db.execute("""SELECT gip_id,boden_m2,boden_pct,grm_kronen_m2
				FROM gip_abschnitte ORDER BY gip_id""").fetchall()
			self.assertEqual(len(raw),2)
			self.assertTrue(all(r[3] is None for r in raw))
			self.assertEqual(db.execute("SELECT COUNT(*) FROM nicht_zugeordnet"
				).fetchone()[0],1)
			self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],
				"ok")
			ext={r[1] for r in db.execute(
				"PRAGMA table_info(gip_abschnitte)")}
			self.assertIn("boden_58_m2",ext)
			self.assertIn("grm_kronen_pct",ext)
			self.assertEqual(db.execute(
				"SELECT COUNT(*) FROM rtree_gip_abschnitte_geom").fetchone()[0],2)
		with self.assertRaisesRegex(FileExistsError,"existiert bereits"):
			self.run_it("boden")
		self.assertEqual(out["status"].count("NICHT"),1)

	def test_crown_complete_mask_measured_independently(self):
		with patch("scripts.wienwide_gip_greening.read_grm",
			return_value=(self.crown,{"sha256":"a"*64,
				"baumschicht_m2":self.crown.area,
				"png_sha256":{"x000_y000":"b"*64}})) as mock:
			out=self.run_it("voll",self.root/"grm")
		self.assertEqual(mock.call_count,1)
		self.assertAlmostEqual(out["grm_kronen_m2"],
			self.crown.intersection(self.first.union(self.second)).area,
			delta=.001)
		with sqlite3.connect(self.root/"voll"/"gip_abschnitte_begruenung.gpkg") as db:
			self.assertAlmostEqual(db.execute(
				"SELECT SUM(grm_kronen_m2) FROM gip_abschnitte").fetchone()[0],
				out["grm_kronen_m2"],delta=.001)
		self.assertTrue((self.root/"voll"/"begruenung_bericht.json").exists())

	def test_missing_grm_mask_aborts_all_outputs_not_counted_zero(self):
		with self.assertRaisesRegex(FileNotFoundError,"Baumschichtmaske fehlt"):
			self.run_it("unfertig",self.root/"missinggrm")
		self.assertFalse((self.root/"unfertig").exists())

	def test_stale_fmzk_and_stale_qa_rejected(self):
		self.fmzk.write_bytes(b"changed")
		with self.assertRaisesRegex(ValueError,"FMZK seit"):
			self.run_it("changed")
		self.assertFalse((self.root/"changed").exists())
		self.fmzk.write_bytes(b"local unmodified fmzk test source")
		with sqlite3.connect(self.qa) as db:
			db.execute("UPDATE qa_provenienz SET value='\"no\"' "
				"WHERE key='partition_sha256'")
		with self.assertRaisesRegex(ValueError,"QA-GeoPackage gehört"):
			self.run_it("changedqa")
		self.assertFalse((self.root/"changedqa").exists())


if __name__=="__main__":
	unittest.main()
