"""Tests des überlappenden SIS-WFS-Cache ohne Netzabrufe."""
import json
import lzma
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from shapely.geometry import box
from scripts.sis_wien_wfs import (OversizedTileError, feature_identity,
	fetch_tile, fetch_tile_parts, merge_cached, split_bounds, tiles, validate)


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

	def test_overfull_logical_tile_is_split_into_audited_part_requests(self):
		with tempfile.TemporaryDirectory() as folder:
			root = Path(folder)
			bounds = (0,0,1900,1900)
			calls = []
			def fake_fetch(name, request_bounds, cache):
				calls.append((name,request_bounds))
				if name == "root":
					raise OversizedTileError("root: 10000 Features")
				return Path(cache)/(name+".geojson.xz"),10,True
			with patch("scripts.sis_wien_wfs.fetch_tile",side_effect=fake_fetch):
				parts,count,downloaded = fetch_tile_parts("root",bounds,root)
			self.assertEqual(count,40)
			self.assertTrue(downloaded)
			self.assertEqual(len(parts),4)
			self.assertEqual([request for _,request in calls[1:]],list(split_bounds(bounds)))
			self.assertEqual(sum(box(*request).area for _,request in calls[1:]),box(*bounds).area)
			manifest = json.loads((root/"root.parts.json").read_text())
			self.assertEqual(manifest["bbox_31256"],list(bounds))
			self.assertEqual(len(manifest["parts"]),4)

	def test_truncated_http_200_json_is_split_and_only_valid_parts_cached(self):
		with tempfile.TemporaryDirectory() as folder:
			root = Path(folder)
			bounds = (0,0,1900,1900)
			truncated = (
				b'{"type":"FeatureCollection","features":[{"type":"Feature",'
				b'"properties":{"BELAG":"' + b'X' * 2048
			)
			valid = json.dumps({"type":"FeatureCollection",
				"features":[feature(1)]}).encode("utf-8")
			calls = []
			def fake_urlopen(req, timeout):
				calls.append(req.full_url)
				response = MagicMock()
				response.read.return_value = truncated if len(calls) == 1 else valid
				response.__enter__.return_value = response
				return response
			with patch("scripts.sis_wien_wfs.urlopen", side_effect=fake_urlopen):
				parts,count,downloaded = fetch_tile_parts("root",bounds,root)
				self.assertEqual(count,4)
				self.assertTrue(downloaded)
				self.assertEqual(len(calls),5)
				self.assertEqual(len(parts),4)
				self.assertFalse((root/"root.geojson.xz").exists())
				self.assertFalse((root/"root.json").exists())
				self.assertEqual(len(list(root.glob("*.geojson.xz"))),4)
				parts2,count2,downloaded2 = fetch_tile_parts("root",bounds,root)
				self.assertEqual(count2,4)
				self.assertFalse(downloaded2)
				self.assertEqual(len(parts2),4)
				self.assertEqual(len(calls),5)

	def test_json_syntax_error_inside_body_does_not_trigger_split(self):
		with self.assertRaises(ValueError) as caught:
			validate(b'{"type": INVALID, "features": []}',tile="bad")
		self.assertNotIsInstance(caught.exception,OversizedTileError)

	def test_transport_limit_is_an_oversized_tile_for_recursive_split(self):
		with tempfile.TemporaryDirectory() as folder:
			response = MagicMock()
			response.read.return_value = b"abc"
			response.__enter__.return_value = response
			with patch("scripts.sis_wien_wfs.MAX_BYTES", 2), patch(
				"scripts.sis_wien_wfs.urlopen", return_value=response):
				with self.assertRaisesRegex(OversizedTileError, "TeilKacheln|Teilkacheln"):
					fetch_tile("large", (0,0,1,1), Path(folder))


if __name__=="__main__":
	unittest.main()
