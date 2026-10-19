"""Dauerhafter Wien-Cache prüft nur AOI/Raster, ohne GIP-Abhängigkeit."""
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pyproj import Transformer
from shapely.geometry import box,mapping
from shapely.ops import transform

from scripts.verify_wien_cache import verify
from scripts.wienwide_grid import build_manifest,write_manifest


class ViennaCacheTests(unittest.TestCase):
	def test_grid_cache(self):
		with TemporaryDirectory() as folder:
			root=Path(folder)
			cache=root/"cache"/"wien"
			cache.mkdir(parents=True)
			to_metric=Transformer.from_crs(
				"EPSG:4326","EPSG:31256",always_xy=True).transform
			to_wgs=Transformer.from_crs(
				"EPSG:31256","EPSG:4326",always_xy=True).transform
			x,y=to_metric(16.36,48.22)
			x=math.floor(x/1000)*1000+100
			y=math.floor(y/1000)*1000+100
			aoi=cache/"aoi.geojson"
			aoi.write_text(json.dumps(mapping(transform(
				to_wgs,box(x,y,x+15,y+15)))))
			manifest=cache/"raster.json"
			write_manifest(manifest,build_manifest(aoi,size=1000,halo=75))
			report=verify(cache)
			self.assertEqual(report["tiles"],1)
			self.assertEqual(report["tile_size_m"],1000)
			with self.assertRaisesRegex(ValueError,"Kachelgröße"):
				verify(cache,tile_m=250)


if __name__=="__main__":
	unittest.main()
