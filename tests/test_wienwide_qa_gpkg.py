"""Synthetische GeoPackage-QA-Tests ohne Online-Daten und GDAL-Abhängigkeit."""
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import unittest

from pyproj import Transformer
from shapely.geometry import box, mapping
from shapely.ops import transform
from shapely.wkb import dumps, loads

from scripts.wienwide_grid import build_manifest,read_manifest,write_manifest,checksum
from scripts.wienwide_partition import connect_results,write_tile
from scripts.wienwide_street import save_street_tile
from scripts.wienwide_qa_gpkg import export,LAYERS


class WienQaGpkgTests(unittest.TestCase):
	def setUp(self):
		self.tmp=tempfile.TemporaryDirectory()
		self.addCleanup(self.tmp.cleanup)
		self.root=Path(self.tmp.name)
		project=Transformer.from_crs("EPSG:4326","EPSG:31256",always_xy=True)
		reverse=Transformer.from_crs("EPSG:31256","EPSG:4326",always_xy=True).transform
		x,y=project.transform(16.365,48.225)
		x=math.floor(x/250)*250+75
		y=math.floor(y/250)*250+75
		self.aoi=box(x,y,x+80,y+80)
		geo=self.root/"aoi.geojson"
		geo.write_text(json.dumps(mapping(transform(reverse,self.aoi))),
			encoding="utf-8")
		self.manifest_file=self.root/"raster.json"
		write_manifest(self.manifest_file,build_manifest(geo,size=250,halo=75))
		manifest,actual_aoi=read_manifest(self.manifest_file)
		self.assertEqual(len(manifest["tiles"]),1)
		self.tile=manifest["tiles"][0]
		self.aoi=actual_aoi
		self.street_root=self.root/"street"
		self.street_path=self.street_root/self.tile["id"]/"street.sqlite"
		save_street_tile(self.street_path,self.aoi,{
			"schema_version":"1","crs":"EPSG:31256",
			"tile_id":self.tile["id"],
			"strassenraum_regel_version":"fmzk-core-21-23-24-25-33-39-nfl-95-65-v2"})
		self.gip=self.root/"gip.sqlite"
		with sqlite3.connect(self.gip) as db:
			db.executescript("""CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
				CREATE TABLE axes(gip TEXT PRIMARY KEY,name TEXT,fow INTEGER,
					node_from TEXT,node_to TEXT);""")
			db.execute("INSERT INTO meta VALUES (?,?)",(
				"manifest_sha256",json.dumps(checksum(self.manifest_file))))
			db.execute("INSERT INTO axes VALUES (?,?,?,?,?)",(
				"1001","Pilotstraße",3,"2","3"))
		self.partition=self.root/"aufteilung.sqlite"
		x0,y0,x1,y1=self.aoi.bounds
		dx=(x1-x0)/4
		pieces=[self.aoi.intersection(box(x0+i*dx-1 if i else x0-10,
			y0-10,x0+(i+1)*dx if i<3 else x1+10,y1+10))
			for i in range(4)]
		# Exact core division, do not let the helper include overlapping strips.
		pieces=[self.aoi.intersection(box(x0+i*dx,y0-10,
			x0+(i+1)*dx,y1+10)) for i in range(4)]
		self.pieces=pieces
		with connect_results(self.partition,create=True) as db:
			db.executemany("INSERT INTO config VALUES (?,?)",[
				("manifest_sha256",checksum(self.manifest_file)),
				("gip_sha256",checksum(self.gip)),
				("schema_version","1"),
			])
			assigned={"1001":pieces[0]}
			unresolved={"knotenbereich":pieces[1],
				"sonderachse":pieces[2],
				"nicht_zugeordnet":pieces[3]}
			stats={"strassenraum_m2":self.aoi.area,
				"zugeordnet_m2":pieces[0].area,
				"ungeklaert_m2":sum(g.area for g in pieces[1:]),
				"fehlend_m2":0,"overlap_m2":0,"ausserhalb_m2":0,
				"toleranz_m2":.05,"sites":10,"knoten":1}
			write_tile(db,self.tile["id"],checksum(self.street_path),
				assigned,unresolved,stats,.01)
		self.dest=self.root/"qa.gpkg"

	def _export(self):
		return export(self.manifest_file,self.gip,self.street_root,
			self.partition,self.dest)

	def test_four_real_gpkg_layers_exact_areas_and_spatial_indices(self):
		report=self._export()
		self.assertTrue(self.dest.exists())
		self.assertEqual(report["kacheln"],1)
		self.assertEqual(set(report["layer_anzahl"]),set(LAYERS))
		self.assertTrue(all(n==1 for n in report["layer_anzahl"].values()))
		self.assertAlmostEqual(sum(report["layer_flaeche_m2"].values()),
			self.aoi.area,delta=.01)
		with sqlite3.connect(self.dest) as db:
			self.assertEqual(db.execute("PRAGMA application_id").fetchone()[0],
				1196444487)
			self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0],10200)
			rows=db.execute("""SELECT table_name FROM gpkg_geometry_columns
				ORDER BY table_name""").fetchall()
			self.assertEqual({r[0] for r in rows},set(LAYERS))
			self.assertEqual(db.execute(
				"SELECT COUNT(*) FROM gpkg_extensions WHERE extension_name='gpkg_rtree_index'"
			).fetchone()[0],4)
			for i,layer in enumerate(LAYERS):
				data=db.execute(f'SELECT geom,kachel_id,kategorie,gip_id,'
					f'strassenname,fow,flaeche_m2 FROM "{layer}"').fetchall()
				self.assertEqual(len(data),1)
				blob,tid,category,gid,name,fow,area=data[0]
				self.assertEqual(blob[:4],b"GP\x00\x03")
				self.assertEqual(blob[8:40] and len(blob)>40,True)
				geometry=loads(blob[40:])
				self.assertEqual(geometry.geom_type,"MultiPolygon")
				self.assertTrue(geometry.is_valid)
				self.assertTrue(geometry.equals(self.pieces[i]))
				self.assertAlmostEqual(area,self.pieces[i].area,delta=.01)
				self.assertEqual(tid,self.tile["id"])
				if layer=="gip_abschnitte":
					self.assertEqual((category,gid,name,fow),
						("abschnitt","1001","Pilotstraße",3))
				else:
					self.assertIsNone(gid)
					self.assertIsNone(fow)
				self.assertEqual(db.execute(f'SELECT COUNT(*) '
					f'FROM "rtree_{layer}_geom"').fetchone()[0],1)
			meta=dict(db.execute("SELECT key,value FROM qa_provenienz"))
			self.assertEqual(json.loads(meta["crs"]),"EPSG:31256")
			self.assertEqual(
				json.loads(meta["gip_sha256"]),checksum(self.gip))
			self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],"ok")
		with self.assertRaisesRegex(FileExistsError,"existiert bereits"):
			self._export()

	def test_stale_street_rejected_without_partial_export(self):
		self.street_path.write_bytes(b"changed")
		with self.assertRaisesRegex(ValueError,"Quelldatei verändert"):
			self._export()
		self.assertFalse(self.dest.exists())
		self.assertFalse(self.dest.with_suffix(".gpkg.tmp").exists())

	def test_missing_gip_axis_and_fow_mismatch_abort(self):
		with sqlite3.connect(self.gip) as db:
			db.execute("UPDATE axes SET fow=4")
		# The changed GIP file has a different SHA than in partition config.
		with self.assertRaisesRegex(ValueError,"anderem Manifest/GIP"):
			self._export()
		self.assertFalse(self.dest.exists())

	def test_invalid_part_area_or_category_never_written(self):
		with sqlite3.connect(self.partition) as db:
			db.execute("UPDATE parts SET area=area+15 WHERE kind='abschnitt'")
		with self.assertRaisesRegex(ValueError,"WKB-Fläche"):
			self._export()
		self.assertFalse(self.dest.exists())

	def test_unrecognized_unresolved_category_aborts_atomically(self):
		with sqlite3.connect(self.partition) as db:
			db.execute("""UPDATE parts SET gip_id='unbekannte_kategorie'
				WHERE kind='ungeklaert' AND gip_id='sonderachse'""")
		with self.assertRaisesRegex(ValueError,"Unbekannte QA-Gruppe"):
			self._export()
		self.assertFalse(self.dest.exists())


if __name__=="__main__":
	unittest.main()
