"""Offline-Tests für den zentralen, wiederaufnehmbaren SIS-Wien-Index."""
import json
import lzma
from pathlib import Path
import sqlite3
import tempfile
import unittest

from shapely.geometry import Polygon, mapping
from scripts.sis_wien_index import (MISSING_BELAG_CODE, MISSING_TYPE_CODE,
	connect, import_tile, verify_complete)
from scripts.sis_wien_source import mask
from pyproj import Transformer
from shapely.ops import transform


class SISWienIndexTests(unittest.TestCase):
	def test_dedup_and_complete_geometry_across_tiles(self):
		with tempfile.TemporaryDirectory() as root:
			root = Path(root)
			geo = {"type":"FeatureCollection","features":[{
				"type":"Feature","id":"SISBELAGOGD.11",
				"properties":{"OBJECTID":11,"SIS_ID":"a","TYPE":"G",
					"BELAG":"WI","BELAG_TXT":"Wiese"},
				"geometry":mapping(Polygon([
					(16.35,48.21),(16.351,48.21),
					(16.351,48.211),(16.35,48.211)]))
			}]}
			cache = root/"tile.geojson.xz"
			cache.write_bytes(lzma.compress(
				json.dumps(geo).encode("utf-8"),preset=6))
			with connect(root/"wien.sqlite") as db:
				a = import_tile(db,"a",(100,100,200,200),cache)
				b = import_tile(db,"b",(190,100,290,200),cache)
				retry = import_tile(db,"a",(100,100,200,200),cache)
				self.assertEqual(a["neu"],1)
				self.assertEqual(b["duplikate"],1)
				self.assertEqual(retry["status"],"vorhanden")
				self.assertEqual(db.execute("SELECT COUNT(*) FROM features").fetchone()[0],1)
				self.assertEqual(db.execute("SELECT COUNT(*) FROM feature_index").fetchone()[0],1)
				to_m = Transformer.from_crs("EPSG:4326","EPSG:31256",
					always_xy=True).transform
				full = transform(to_m,Polygon(geo["features"][0]["geometry"]["coordinates"][0]))
				self.assertAlmostEqual(mask(db,full).area,full.area,delta=.01)
				self.assertAlmostEqual(mask(db,full,{"WI"}).area,full.area,delta=.01)

	def test_incomplete_tile_set_is_rejected(self):
		with tempfile.TemporaryDirectory() as root:
			with connect(Path(root)/"wien.sqlite") as db:
				grid = [("a",(0,0,1900,1900))]
				with self.assertRaisesRegex(ValueError,"unvollständig"):
					verify_complete(db,grid)
				db.execute("INSERT INTO imported_tiles VALUES (?,?,?,?,?,?)",
					("a","sha",json.dumps([0,0,1900,1900]),0,0,0))
				self.assertTrue(verify_complete(db,grid))
				with self.assertRaisesRegex(ValueError,"abweichend"):
					verify_complete(db,[("a",(0,0,1800,1800))])

	def test_conflicting_id_rolls_back_whole_tile(self):
		with tempfile.TemporaryDirectory() as root:
			root = Path(root)
			def tile(oid,belag):
				return {"type":"Feature","id":f"f.{oid}",
					"properties":{"OBJECTID":oid,"SIS_ID":"s","TYPE":"G",
						"BELAG":belag,"BELAG_TXT":"Belag"},
					"geometry":mapping(Polygon([
						(16.35,48.21),(16.351,48.21),
						(16.351,48.211),(16.35,48.211)]))}
			def write(name,features):
				file = root/(name+".geojson.xz")
				file.write_bytes(lzma.compress(json.dumps({
					"type":"FeatureCollection","features":features}).encode(),preset=6))
				return file
			a = write("a",[tile(1,"WI")])
			b = write("b",[tile(2,"WI"),tile(1,"AS")])
			with connect(root/"wien.sqlite") as db:
				import_tile(db,"a",(0,0,10,10),a)
				with self.assertRaisesRegex(ValueError,"widersprüchliche"):
					import_tile(db,"b",(10,0,20,10),b)
				self.assertEqual(db.execute("SELECT COUNT(*) FROM features").fetchone()[0],1)
				self.assertEqual(db.execute("SELECT COUNT(*) FROM imported_tiles").fetchone()[0],1)

	def test_missing_type_is_retained_even_for_larger_area(self):
		with tempfile.TemporaryDirectory() as folder:
			root = Path(folder)
			def feature(identifier, coordinates):
				return {"type":"Feature","id":f"SISBELAGOGD.{identifier}",
					"properties":{"OBJECTID":identifier,"SIS_ID":identifier,
						"TYPE":None,"BELAG":None,"BELAG_TXT":None},
					"geometry":mapping(Polygon(coordinates))}
			def write(name, items):
				path = root/(name+".geojson.xz")
				path.write_bytes(lzma.compress(json.dumps({
					"type":"FeatureCollection","features":items}).encode(),preset=6))
				return path
			# Ein fehlender TYPE darf V2-Straßenraum nicht ausschließen:
			# Alle SIS-Polygone zählen unabhängig vom TYPE.
			tiny = write("tiny",[feature(1,[
				(16.19464840,48.22599006),(16.19464844,48.22599009),
				(16.19464834,48.22599011),(16.19464840,48.22599006)])])
			large = write("large",[feature(2,[
				(16.194,48.225),(16.195,48.225),
				(16.195,48.226),(16.194,48.226),(16.194,48.225)])])
			with connect(root/"wien.sqlite") as db:
				result = import_tile(db,"tiny",(0,0,10,10),tiny)
				self.assertEqual(result["neu"],1)
				event = db.execute("SELECT missing_fields_json,metric_area_m2,treatment "
					"FROM classification_events").fetchone()
				self.assertEqual(json.loads(event[0]),["TYPE","BELAG","BELAG_TXT"])
				self.assertLess(event[1],.01)
				self.assertEqual(event[2],"fehlender_BELAG_konservativ_nicht_begruent")
				second = import_tile(db,"large",(10,0,20,10),large)
				self.assertEqual(second["neu"],1)
				self.assertEqual(db.execute("SELECT COUNT(*) FROM imported_tiles").fetchone()[0],2)
				self.assertEqual(db.execute("SELECT COUNT(*) FROM excluded_features").fetchone()[0],0)
				self.assertEqual(db.execute("SELECT type FROM features ORDER BY id DESC").fetchone()[0],MISSING_TYPE_CODE)

	def test_volatile_wfs_java_reference_does_not_make_a_conflicting_duplicate(self):
		with tempfile.TemporaryDirectory() as folder:
			root = Path(folder)
			def write(name, java_reference):
				feature = {"type":"Feature","id":"SISBELAGOGD.11",
					"properties":{"OBJECTID":11,"SIS_ID":"a","TYPE":"FF",
						"BELAG":"BT","BELAG_TXT":"Tragschicht",
						"SE_ANNO_CAD_DATA":java_reference},
					"geometry":mapping(Polygon([
						(16.35,48.21),(16.351,48.21),
						(16.351,48.211),(16.35,48.211)]))}
				path = root/(name+".geojson.xz")
				path.write_bytes(lzma.compress(json.dumps({
					"type":"FeatureCollection","features":[feature]}).encode(),preset=6))
				return path
			with connect(root/"wien.sqlite") as db:
				first = import_tile(db,"a",(0,0,10,10),write("a","[B@first"))
				second = import_tile(db,"b",(10,0,20,10),write("b","[B@second"))
				self.assertEqual(first["neu"],1)
				self.assertEqual(second["neu"],0)
				self.assertEqual(second["duplikate"],1)
				self.assertEqual(db.execute("SELECT COUNT(*) FROM features").fetchone()[0],1)

	def test_older_index_contract_requires_explicit_cache_rebuild(self):
		with tempfile.TemporaryDirectory() as folder:
			path = Path(folder)/"wien.sqlite"
			with sqlite3.connect(path) as db:
				db.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
				db.execute("INSERT INTO metadata VALUES ('schema','sis-wien-index-v2')")
			with self.assertRaisesRegex(ValueError,"neu aufgebaut"):
				connect(path)

	def test_missing_belag_remains_in_street_area_but_is_conservatively_non_green(self):
		with tempfile.TemporaryDirectory() as folder:
			root = Path(folder)
			geometry = Polygon([
				(16.35,48.21),(16.351,48.21),
				(16.351,48.211),(16.35,48.211)])
			feature = {"type":"Feature","id":"SISBELAGOGD.13",
				"properties":{"OBJECTID":13,"SIS_ID":"missing-belag","TYPE":"FF",
					"BELAG":None,"BELAG_TXT":None},"geometry":mapping(geometry)}
			path = root/"tile.geojson.xz"
			path.write_bytes(lzma.compress(json.dumps({
				"type":"FeatureCollection","features":[feature]}).encode(),preset=6))
			with connect(root/"wien.sqlite") as db:
				result = import_tile(db,"a",(0,0,10,10),path)
				self.assertEqual(result["neu"],1)
				self.assertEqual(result["fehlender_belag"],1)
				self.assertEqual(db.execute("SELECT belag FROM features").fetchone()[0],
					MISSING_BELAG_CODE)
				self.assertEqual(db.execute("SELECT COUNT(*) FROM classification_events").fetchone()[0],1)
				to_m = Transformer.from_crs("EPSG:4326","EPSG:31256",
					always_xy=True).transform
				core = transform(to_m,geometry)
				self.assertAlmostEqual(mask(db,core).area,core.area,delta=.01)
				self.assertIsNone(mask(db,core,{"WI"}))


if __name__=="__main__":
	unittest.main()
