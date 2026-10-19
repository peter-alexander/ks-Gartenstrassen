"""Synthetic tests of tiled LINEAR_USE Voronoi debug output."""
import json
import math
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pyproj import Transformer
from shapely.geometry import LineString, Polygon, box, mapping, shape
from shapely.errors import GEOSException
from shapely.ops import transform
from shapely.strtree import STRtree
from shapely.wkb import dumps

from scripts.build_linear_use_voronoi import _tile_polygons, _safe_clip, _robust_voronoi, build
from scripts.wienwide_grid import build_manifest, write_manifest, load_aoi
from scripts.wienwide_street import save_street_tile


class LinearUseVoronoiTests(unittest.TestCase):
	def test_two_parallel_axes_partition_tile(self):
		lines=[LineString([(0,20),(100,20)]),
			LineString([(0,80),(100,80)])]
		polygons=dict(_tile_polygons(["a","b"],lines,STRtree(lines),
			box(0,0,100,100),spacing_m=20,halo_m=50))
		self.assertEqual(set(polygons),{"a","b"})
		self.assertAlmostEqual(polygons["a"].area,5000,places=5)
		self.assertAlmostEqual(polygons["b"].area,5000,places=5)
		self.assertAlmostEqual(polygons["a"].intersection(
			polygons["b"]).area,0,places=5)
		self.assertAlmostEqual(polygons["a"].union(
			polygons["b"]).area,10000,places=5)

	def test_geos_voronoi_failure_retries_without_losing_owners(self):
		seeds={(0.0,0.0):"a",(10.0,0.0):"b",
			(0.0,10.0):"c",(10.0,10.0):"d"}
		from shapely import voronoi_polygons as real
		calls=[]
		def flaky(*args,**kwargs):
			calls.append(args)
			if len(calls)==1:
				raise GEOSException("Invalid number of points in LinearRing")
			return real(*args,**kwargs)
		with patch("scripts.build_linear_use_voronoi.voronoi_polygons",
				side_effect=flaky):
			owners,cells=_robust_voronoi(seeds,box(-20,-20,20,20))
		self.assertEqual(len(calls),2)
		self.assertEqual(owners,["a","b","c","d"])
		self.assertEqual(len(cells.geoms),4)

	def test_precision_retry_deduplicates_points_and_owners(self):
		seeds={(0.0,0.0):"b",(0.0001,0.0001):"a",
			(10.0,0.0):"c",(0.0,10.0):"d"}
		from shapely import voronoi_polygons as real
		calls=0
		def flaky(*args,**kwargs):
			nonlocal calls
			calls+=1
			if calls==1:
				raise GEOSException("Invalid LinearRing")
			return real(*args,**kwargs)
		with patch("scripts.build_linear_use_voronoi.voronoi_polygons",
				side_effect=flaky):
			owners,cells=_robust_voronoi(seeds,box(-20,-20,20,20))
		self.assertEqual(len(owners),3)
		self.assertIn("a",owners)
		self.assertNotIn("b",owners)
		self.assertEqual(len(cells.geoms),3)

	def test_invalid_cell_repairs_before_clipping(self):
		cell=Polygon([(0,0),(10,10),(0,10),(10,0),(0,0)])
		self.assertFalse(cell.is_valid)
		result=_safe_clip(cell,box(-1,-1,11,11))
		self.assertTrue(result.is_valid)
		self.assertGreater(result.area,0)

	def test_sparse_tile_far_from_axes(self):
		lines=[LineString([(5000,0),(5050,0)]),
			LineString([(5000,100),(5050,100)])]
		core=box(0,0,100,100)
		pieces=list(_tile_polygons(["a","b"],lines,STRtree(lines),
			core,spacing_m=20,halo_m=50))
		self.assertTrue(pieces)
		from shapely import union_all
		self.assertAlmostEqual(union_all([p for _,p in pieces]).area,
			core.area,delta=0.01)

	def test_single_short_axis_covers_tile(self):
		lines=[LineString([(5000,0),(5000.01,0)])]
		core=box(0,0,100,100)
		pieces=list(_tile_polygons(["a"],lines,STRtree(lines),
			core,spacing_m=20,halo_m=50))
		self.assertEqual(len(pieces),1)
		self.assertEqual(pieces[0][0],"a")
		self.assertAlmostEqual(pieces[0][1].area,core.area,places=5)

	def test_debug_geojson_from_sqlite(self):
		with TemporaryDirectory() as tmp:
			root=Path(tmp)
			cache=root/"linear_use.sqlite"
			aoi_path=root/"aoi.geojson"
			output=root/"voronoi.geojson"
			manifest_path=root/"raster.json"
			sis_root=root/"strassenraum"
			to_wgs=Transformer.from_crs(31256,4326,always_xy=True).transform
			to_m=Transformer.from_crs(4326,31256,always_xy=True).transform
			x,y=to_m(16.36,48.22)
			x=math.floor(x/500)*500
			y=math.floor(y/500)*500
			aoi=box(x,y,x+500,y+500)
			aoi_path.write_text(json.dumps(mapping(transform(to_wgs,aoi))),
				encoding="utf-8")
			manifest=build_manifest(aoi_path,size=500,halo=75)
			write_manifest(manifest_path,manifest)
			tile=manifest["tiles"][0]
			sis=box(x,y,x+500,y+250).intersection(load_aoi(aoi_path))
			save_street_tile(sis_root/tile["id"]/"street.sqlite",sis,{
				"schema_version":"1","crs":"EPSG:31256",
				"strassenraum_regel_version":"sis-belagsflaechen-v2"},
				allow_empty=True)
			with sqlite3.connect(cache) as db:
				db.execute("CREATE TABLE edge_axes(edge_id TEXT PRIMARY KEY, wkb BLOB)")
				db.executemany("INSERT INTO edge_axes VALUES (?,?)",[
					("a",dumps(LineString([(x,y+150),(x+500,y+150)]))),
					("b",dumps(LineString([(x,y+350),(x+500,y+350)]))),
				])
			number=build(cache,aoi_path,output,sis_manifest=manifest_path,
				sis_root=sis_root,tile_m=500,halo_m=250,
				spacing_m=50,max_tiles=1)
			doc=json.loads(output.read_text(encoding="utf-8"))
			self.assertEqual(doc["type"],"FeatureCollection")
			self.assertGreaterEqual(number,2)
			self.assertEqual(number,len(doc["features"]))
			self.assertTrue(all(feature["properties"]["debug"] for feature
				in doc["features"]))
			self.assertEqual({feature["properties"]["edge_id"]
				for feature in doc["features"]},{"a","b"})
			self.assertTrue(all(shape(feature["geometry"]).is_valid
				for feature in doc["features"]))
			self.assertTrue(all(transform(
					Transformer.from_crs(4326,31256,always_xy=True).transform,
					shape(feature["geometry"])).difference(sis).area < 0.01
					for feature in doc["features"]))
			with self.assertRaises(FileExistsError):
				build(cache,aoi_path,output,sis_manifest=manifest_path,
					sis_root=sis_root,tile_m=500,halo_m=250,
					spacing_m=50,max_tiles=1)


if __name__=="__main__":
	unittest.main()
