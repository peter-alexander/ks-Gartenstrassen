"""Offline-Tests für den zentralen, wiederaufnehmbaren SIS-Wien-Index."""
import json
import lzma
from pathlib import Path
import tempfile
import unittest

from shapely.geometry import Polygon, mapping
from scripts.sis_wien_index import connect, import_tile
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


if __name__=="__main__":
	unittest.main()
