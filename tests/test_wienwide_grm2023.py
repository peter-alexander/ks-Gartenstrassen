"""Bezirksweise GRM2023-WMS-Abdeckung: echte PNGs, lokale Caches, kein Netzwerk."""
from io import BytesIO
import json
import math
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from pyproj import Transformer
from shapely.geometry import box,mapping
from shapely.ops import transform

from scripts.wienwide_grid import build_manifest,write_manifest,read_manifest,checksum
from scripts.wienwide_grm2023 import (
	_verify_transparent_outside_aoi,build,chunks,decode_chunk,fetch,
	mask_path,read_mask,verify_chunk,
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
		cached,_=read_mask(self.root_cache,self.tile,
			manifest=self.manifest,aoi=self.aoi,
			manifest_sha256=checksum(self.manifest))
		self.assertTrue(cached.equals(geom))
		with self.assertRaisesRegex(ValueError,"anderem Bezirksraster"):
			read_mask(self.root_cache,self.tile,
				manifest=self.manifest,aoi=self.aoi,
				manifest_sha256="0"*64)
		self.assertEqual(len(meta["png_sha256"]),1)
		# Resume must not perform additional GetMap requests.
		with patch("scripts.wienwide_grm2023.request_bytes",
			side_effect=AssertionError("no network")):
			self.assertEqual(fetch(self.manifest,self.root_cache,
				pause_s=0)["neu_geladen"],0)
		self.assertEqual(build(self.manifest,self.root_cache)["fertige_kacheln"],1)

	def test_wienwide_requests_exceed_legacy_global_limit_but_still_cache(self):
		# Drei Kacheln mit je einem Bild überschreiten künstlich die
		# Grenze 2: Diese darf NICHT mehr für die gesamte AOI gelten.
		# Pro Kachel bleibt nur ein kleines, sicher begrenztes Bild.
		tiles=[{**self.tile,"id":f"test_kachel_{n}"}
			for n in range(3)]
		manifest={"tiles":tiles}
		png=self._png()
		def one_chunk(tile,aoi):
			return [(self.name,self.geo,self.url)]
		with patch("scripts.wienwide_grm2023.MAX_CHUNKS",2), patch(
			"scripts.wienwide_grm2023.read_manifest",
			return_value=(manifest,self.aoi)), patch(
			"scripts.wienwide_grm2023.chunks",
			side_effect=one_chunk), patch(
			"scripts.wienwide_grm2023.parse_capabilities",
			return_value={"unterstuetzte_srs":["EPSG:31256"]}), patch(
			"scripts.wienwide_grm2023.request_bytes",
			side_effect=[b"cap",png,png,png]) as net, patch(
			"scripts.wienwide_grm2023.sleep") as wait:
			result=fetch(self.manifest,self.root_cache,pause_s=.5)
			self.assertEqual(result["kacheln"],3)
			self.assertEqual(result["wms_bilder"],3)
			self.assertEqual(result["neu_geladen"],3)
			self.assertEqual(net.call_count,4)  # 1 Caps + 3 GetMap
			self.assertEqual(wait.call_count,2)
			for tile in tiles:
				verify_chunk(self.root_cache,tile,
					self.name,self.geo,self.url)
		with patch("scripts.wienwide_grm2023.MAX_CHUNKS",2), patch(
			"scripts.wienwide_grm2023.read_manifest",
			return_value=(manifest,self.aoi)), patch(
			"scripts.wienwide_grm2023.chunks",
			side_effect=one_chunk), patch(
			"scripts.wienwide_grm2023.request_bytes",
			side_effect=AssertionError("Geprüfter Cache muss offline bleiben")):
			resumed=fetch(self.manifest,self.root_cache,pause_s=0)
		self.assertEqual(resumed["wms_bilder"],3)
		self.assertEqual(resumed["neu_geladen"],0)

	def test_wms_request_limit_remains_enforced_within_a_tile(self):
		# Eine 1000-m-Vollkachel braucht vier 500-m-GetMaps;
		# ein bewusst niedriger Kachelgrenzwert muss sie abweisen.
		large={"id":"synthetisch","bounds_31256":[0,0,1000,1000]}
		with patch("scripts.wienwide_grm2023.MAX_CHUNKS",2):
			with self.assertRaisesRegex(ValueError,
				"Zu viele GRM-Anfragen je Kachel"):
				chunks(large,box(0,0,1000,1000))

	def test_transparent_white_outside_actual_aoi_is_not_nodata_inside(self):
		# Durch transparent=TRUE gerenderter WMS-Hintergrund am
		# Bezirksrand, aber innerhalb der AOI ein bekanntes GRM-RGB.
		with Image.new("RGBA",(500,500),(235,235,235,255)) as image:
			image.putpixel((0,0),(255,255,255,0))
			image.putpixel((self.px,self.py),(56,168,0,255))
			buf=BytesIO()
			image.save(buf,format="PNG")
		self._fetch(buf.getvalue())
		geom,stats=decode_chunk(
			self.root_cache/"png"/self.tile["id"]/(self.name+".png"),
			self.geo,label="transparenter Außenrand",core=self.aoi)
		self.assertEqual(stats["transparente_pixel_ausserhalb_aoi"],1)
		self.assertEqual(stats["baum_pixel"],1)
		self.assertAlmostEqual(geom.area,.25,delta=1e-6)
		self.assertEqual(build(self.manifest,self.root_cache)["fertige_kacheln"],1)
		with sqlite3.connect(mask_path(self.root_cache,self.tile)) as db:
			info=dict(db.execute("SELECT key,value FROM metadata"))
		self.assertEqual(info["transparente_pixel_ausserhalb_aoi"],"1")
		rebuilt,_=read_mask(self.root_cache,self.tile,
			manifest=self.manifest,aoi=self.aoi)
		self.assertAlmostEqual(rebuilt.area,.25,delta=.001)

	def test_transparent_white_inside_aoi_aborts_without_zero_mask(self):
		with Image.new("RGBA",(500,500),(235,235,235,255)) as image:
			image.putpixel((self.px,self.py),(255,255,255,0))
			buf=BytesIO()
			image.save(buf,format="PNG")
		self._fetch(buf.getvalue())
		with self.assertRaisesRegex(ValueError,
			"transparentes WMS-Weiß innerhalb Wiener AOI"):
			build(self.manifest,self.root_cache)
		self.assertFalse(mask_path(self.root_cache,self.tile).exists())

	def test_transparency_checks_pixel_footprint_not_only_center(self):
		# Die transparente Zelle [1,2]x[3,4] trifft die
		# AOI [0.9,1.1]x[2.9,3.1] an einem 0,1x0,1-m-Eck.
		# Ihr Zentrum (1.5,3.5) liegt außerhalb: Mittelpunkt-
		# Tests würden diese echte Lücke übersehen.
		geo={"bbox":[0,0,4,4],"width":4,"height":4}
		pixels=[(235,235,235,255)]*16
		pixels[1]=(255,255,255,0)
		with self.assertRaisesRegex(ValueError,"innerhalb Wiener AOI"):
			_verify_transparent_outside_aoi(pixels,geo,
				box(.9,2.9,1.1,3.1),label="Grenzpixel")
		self.assertEqual(
			_verify_transparent_outside_aoi(pixels,geo,
				box(0,0,1,1),label="außerhalb AOI"),1)

	def test_partial_alpha_and_unknown_transparent_rgb_still_abort(self):
		for color in ((56,168,0,128),(0,0,0,0),
				(255,255,255,100),(25,25,25,255)):
			with self.subTest(color=color):
				with Image.new("RGBA",(500,500),(235,235,235,255)) as image:
					image.putpixel((0,0),color)
					buf=BytesIO()
					image.save(buf,format="PNG")
				png=self.root/f"bad-{color[0]}-{color[3]}.png"
				png.write_bytes(buf.getvalue())
				with self.assertRaisesRegex(ValueError,
					"unbekannte/transparente WMS-Farben"):
					decode_chunk(png,self.geo,label="falsche Farbe",
						core=self.aoi)

	def test_transparency_without_aoi_is_not_silently_accepted(self):
		with Image.new("RGBA",(500,500),(235,235,235,255)) as image:
			image.putpixel((0,0),(255,255,255,0))
			buf=BytesIO()
			image.save(buf,format="PNG")
		png=self.root/"without-aoi.png"
		png.write_bytes(buf.getvalue())
		with self.assertRaisesRegex(ValueError,
			"Transparenz ohne gültige AOI"):
			decode_chunk(png,self.geo,label="fehlende AOI")

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
