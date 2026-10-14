"""Bezirksweise GRM2023-WMS-Abdeckung: echte PNGs, lokale Caches, kein Netzwerk."""
from io import BytesIO
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from pyproj import Transformer
from shapely.geometry import box,mapping
from shapely.ops import transform

from scripts.wienwide_grid import build_manifest,write_manifest,read_manifest
from scripts.wienwide_grm2023 import (
	build,chunks,decode_chunk,fetch,mask_path,read_mask,
)


class WienwideGrm2023Tests(unittest.TestCase):
	def setUp(self):
		self.tmp=tempfile.TemporaryDirectory()
		self.addCleanup(self.tmp.cleanup)
		self.root=Path(self.tmp.name)
		t=Transformer.from_crs("EPSG:4326","EPSG:31256",always_xy=True)
		rev=Transformer.from_crs("EPSG:31256","EPSG:4326",
			always_xy=True).transform
		x,y=t.transform(16.365,48.225)
		x=math.floor(x/250)*250+50
		y=math.floor(y/250)*250+50
		aoi=box(x,y,x+10,y+10)
		geo=self.root/"aoi.geojson"
		geo.write_text(json.dumps(mapping(transform(rev,aoi))))
		self.manifest=self.root/"grid.json"
		write_manifest(self.manifest,build_manifest(geo,size=250,halo=75))
		m,self.aoi=read_manifest(self.manifest)
		self.assertEqual(len(m["tiles"]),1)
		self.tile=m["tiles"][0]
		self.root_cache=self.root/"cache"
		self.mapping=chunks(self.tile,self.aoi)
		self.assertEqual(len(self.mapping),1)
		self.name,self.geo,self.url=self.mapping[0]
		self.assertEqual((self.geo["width"],self.geo["height"]),(500,500))
		self.bbox=self.geo["bbox"]
		self.px=int((self.aoi.centroid.x-self.bbox[0])/.5)
		self.py=int((self.bbox[3]-self.aoi.centroid.y)/.5)
		self.assertGreater(self.px,0)
		self.assertGreater(self.py,0)

	def _png(self,*,corrupt=False):
		with Image.new("RGBA",(500,500),(235,235,235,255)) as image:
			color=(25,25,25,255) if corrupt else (56,168,0,255)
			image.putpixel((self.px,self.py),color)
			buf=BytesIO()
			image.save(buf,format="PNG")
		return buf.getvalue()

	def _fetch(self,png):
		with patch("scripts.wienwide_grm2023.request_bytes",
			side_effect=[b"cap",png]) as request, patch(
			"scripts.wienwide_grm2023.parse_capabilities",
			return_value={"unterstuetzte_srs":["EPSG:31256"]}):
			report=fetch(self.manifest,self.root_cache,pause_s=0)
		self.assertEqual(request.call_count,2)
		self.assertEqual(report["neu_geladen"],1)

	def test_covers_exact_aoi_and_recovers_checked_cache(self):
		self._fetch(self._png())
		r=build(self.manifest,self.root_cache)
		self.assertEqual(r["fertige_kacheln"],1)
		self.assertTrue(mask_path(self.root_cache,self.tile).is_file())
		geom,meta=read_mask(self.root_cache,self.tile,
			manifest=self.manifest,aoi=self.aoi)
		self.assertAlmostEqual(geom.area,.25,delta=.001)
		self.assertEqual(len(meta["png_sha256"]),1)
		# Resume must not perform additional GetMap requests.
		with patch("scripts.wienwide_grm2023.request_bytes",
			side_effect=AssertionError("no network")):
			self.assertEqual(fetch(self.manifest,self.root_cache,
				pause_s=0)["neu_geladen"],0)
		self.assertEqual(build(self.manifest,self.root_cache)["fertige_kacheln"],1)

	def test_invalid_color_aborts_without_fake_zero_mask(self):
		self._fetch(self._png(corrupt=True))
		with self.assertRaisesRegex(ValueError,"unbekannte/transparente"):
			build(self.manifest,self.root_cache)
		self.assertFalse(mask_path(self.root_cache,self.tile).exists())

	def test_empty_tree_but_fully_classified_raster_is_valid_zero(self):
		with Image.new("RGBA",(500,500),(235,235,235,255)) as image:
			buf=BytesIO()
			image.save(buf,format="PNG")
		self._fetch(buf.getvalue())
		self.assertEqual(build(self.manifest,self.root_cache)["fertige_kacheln"],1)
		geom,_=read_mask(self.root_cache,self.tile,
			manifest=self.manifest,aoi=self.aoi)
		self.assertEqual(geom.area,0)

	def test_source_mutation_aborts_verified_cache(self):
		self._fetch(self._png())
		build(self.manifest,self.root_cache)
		png=self.root_cache/"png"/self.tile["id"]/(self.name+".png")
		png.write_bytes(b"altered")
		with self.assertRaisesRegex(ValueError,"widersprechen"):
			read_mask(self.root_cache,self.tile,
				manifest=self.manifest,aoi=self.aoi)


if __name__=="__main__":
	unittest.main()
