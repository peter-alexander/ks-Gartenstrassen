"""Tests des überlappenden SIS-WFS-Cache ohne Netzabrufe."""
import json
import lzma
from pathlib import Path
import tempfile
import unittest

from shapely.geometry import box
from scripts.sis_wien_wfs import tiles, feature_identity, merge_cached, validate


def feature(oid):
	return {"type":"Feature","id":f"SISBELAGOGD.{oid}",
		"properties":{"OBJECTID":oid,"SIS_ID":5,"TYPE":"G","BELAG":"AS",
			"BELAG_TXT":"Asphalt"},"geometry":{"type":"Polygon",
			"coordinates":[[[16.4,48.2],[16.401,48.2],[16.401,48.201],
				[16.4,48.201],[16.4,48.2]]]}}


class SISWienWFSTests(unittest.TestCase):
	def test_request_is_below_two_km(self):
		grid = list(tiles(box(10000,340000,14500,344500)))
		self.assertTrue(grid)
		for _,(x0,y0,x1,y1) in grid:
			self.assertEqual(x1-x0,1900)
			self.assertEqual(y1-y0,1900)

	def test_dedup_uses_feature_id_not_sis_id(self):
		with tempfile.TemporaryDirectory() as folder:
			root = Path(folder)
			a,b = root/"a.geojson.xz",root/"b.geojson.xz"
			a.write_bytes(lzma.compress(json.dumps({"type":"FeatureCollection",
				"features":[feature(1),feature(2)]}).encode(), preset=6))
			b.write_bytes(lzma.compress(json.dumps({"type":"FeatureCollection",
				"features":[feature(1),feature(3)]}).encode(), preset=6))
			out = root/"all.geojson.xz"
			result = merge_cached([a,b],out)
			self.assertEqual(result["eindeutige_features"],3)
			self.assertEqual(result["entfernte_dubletten"],1)
			self.assertEqual(len(json.loads(lzma.decompress(out.read_bytes()))["features"]),3)

	def test_conflicting_duplicate_fails_closed(self):
		with tempfile.TemporaryDirectory() as folder:
			root = Path(folder)
			a,b = root/"a.geojson.xz",root/"b.geojson.xz"
			f = feature(1)
			a.write_bytes(lzma.compress(json.dumps({"type":"FeatureCollection","features":[f]}).encode(), preset=6))
			g = feature(1)
			g["properties"]["BELAG"] = "BL"
			b.write_bytes(lzma.compress(json.dumps({"type":"FeatureCollection","features":[g]}).encode(), preset=6))
			with self.assertRaisesRegex(ValueError,"widersprüchliche"):
				merge_cached([a,b],root/"out.geojson.xz")
			self.assertFalse((root/"out.geojson.xz").exists())

	def test_missing_source_identifier_fails(self):
		f = feature(1)
		f.pop("id")
		f["properties"].pop("OBJECTID")
		with self.assertRaisesRegex(ValueError,"sichere Deduplikation"):
			feature_identity(f)


if __name__=="__main__":
	unittest.main()
