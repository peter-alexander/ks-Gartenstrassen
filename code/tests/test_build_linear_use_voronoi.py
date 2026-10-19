"""Synthetic tests of tiled LINEAR_USE Voronoi debug output."""
import json
import math
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pyproj import Transformer
from shapely.geometry import LineString, Polygon, box, mapping, shape
from shapely.ops import transform
from shapely.strtree import STRtree
from shapely.wkb import dumps

from scripts.build_linear_use_voronoi import _tile_polygons, _safe_clip, build


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
			to_wgs=Transformer.from_crs(31256,4326,always_xy=True).transform
			to_m=Transformer.from_crs(4326,31256,always_xy=True).transform
			x,y=to_m(16.36,48.22)
			x=math.floor(x/500)*500
			y=math.floor(y/500)*500
			aoi=box(x,y,x+500,y+500)
			aoi_path.write_text(json.dumps(mapping(transform(to_wgs,aoi))),
				encoding="utf-8")
			with sqlite3.connect(cache) as db:
				db.execute("CREATE TABLE edge_axes(edge_id TEXT PRIMARY KEY, wkb BLOB)")
				db.executemany("INSERT INTO edge_axes VALUES (?,?)",[
					("a",dumps(LineString([(x,y+150),(x+500,y+150)]))),
					("b",dumps(LineString([(x,y+350),(x+500,y+350)]))),
				])
			number=build(cache,aoi_path,output,tile_m=500,halo_m=250,
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
			with self.assertRaises(FileExistsError):
				build(cache,aoi_path,output,tile_m=500,halo_m=250,
					spacing_m=50,max_tiles=1)


if __name__=="__main__":
	unittest.main()
