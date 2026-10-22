"""Historical GIP2 NODE/TURN_USE convex hulls: exact grouping and geometry."""
from pathlib import Path
import sqlite3
import struct
from tempfile import TemporaryDirectory
import unittest

from pyproj import Transformer
from shapely.geometry import Point,LineString,box,MultiPoint
from shapely.ops import transform
from shapely.wkb import dumps

from scripts.cgal_turn_use_hulls import (
	gpkg_geom,load_turn_use_hulls)


def _gpkg(geometry):
	# GeoPackage binary header: magic GP, version 0, little-endian/no
	# envelope, EPSG:4326, followed by little-endian WKB.
	return b"GP"+bytes((0,1))+struct.pack("<i",4326)+dumps(geometry)


def _source(path,*,include_non_collinear=True):
	center=(16.35,48.20)
	with sqlite3.connect(path) as db:
		db.executescript("""
			CREATE TABLE gpkg_contents(table_name TEXT PRIMARY KEY);
			INSERT INTO gpkg_contents VALUES ('NODE'),('TURN_USE');
			CREATE TABLE NODE(
				fid INTEGER PRIMARY KEY,object_id TEXT,geom BLOB);
			CREATE TABLE TURN_USE(
				fid INTEGER PRIMARY KEY,object_id TEXT,via_node_id TEXT,
				base_type INTEGER,geom BLOB);
			CREATE VIRTUAL TABLE rtree_NODE_geom USING rtree(
				id,minx,maxx,miny,maxy);
			CREATE VIRTUAL TABLE rtree_TURN_USE_geom USING rtree(
				id,minx,maxx,miny,maxy);
		""")
		node=Point(*center)
		db.execute("INSERT INTO NODE VALUES (?,?,?)",(1,"junction-1",_gpkg(node)))
		db.execute("INSERT INTO rtree_NODE_geom VALUES (?,?,?,?,?)",
			(1,node.x,node.x,node.y,node.y))
		# All TURN_USE lines participate, including base_type=7.
		data=[
			("t1","junction-1",7,LineString([
				(16.34995,48.20),(16.35,48.20010)])),
			("t2","junction-1",1,LineString([
				(16.35005,48.20),(16.35,48.20010)])),
			("unrelated","other-node",1,LineString([
				(16.3495,48.1995),(16.3505,48.2005)])),
		]
		if not include_non_collinear:
			data=[("t1","junction-1",7,LineString([
				(16.34995,48.20),(16.35,48.20)]))]
		for i,(ident,node_id,base_type,geom) in enumerate(data,1):
			db.execute("INSERT INTO TURN_USE VALUES (?,?,?,?,?)",
				(i,ident,node_id,base_type,_gpkg(geom)))
			minx,miny,maxx,maxy=geom.bounds
			db.execute("INSERT INTO rtree_TURN_USE_geom VALUES (?,?,?,?,?)",
				(i,minx,maxx,miny,maxy))
	return center


class HistoricalTurnUseHullTests(unittest.TestCase):
	def test_hulls_use_all_turn_lines_grouped_by_via_node_id(self):
		with TemporaryDirectory() as root:
			source=Path(root)/"gip_network_ogd.gpkg"
			center=_source(source)
			to_metric=Transformer.from_crs(4326,31256,
				always_xy=True).transform
			aoi=transform(to_metric,box(16.348,48.198,16.352,48.202))
			hulls,report=load_turn_use_hulls(source,aoi)
			self.assertEqual(len(hulls),1)
			self.assertEqual(hulls[0][0],"junction-1")
			self.assertEqual(report["nodes_in_aoi_envelope"],1)
			self.assertEqual(report["turn_use_lines_used"],2)
			self.assertEqual(report["original_polygonal_junction_hulls"],1)
			self.assertEqual(report["hulls_intersecting_aoi"],1)
			original=transform(to_metric,MultiPoint([
				(16.34995,48.20),(16.35,48.20010),
				(16.35005,48.20)]).convex_hull)
			self.assertLess(hulls[0][1].symmetric_difference(original).area,
				1e-6)
			self.assertIn("all_TURN_USE",report["historic_rule"])

	def test_collinear_turn_use_is_not_artificially_buffered(self):
		with TemporaryDirectory() as root:
			source=Path(root)/"gip_network_ogd.gpkg"
			_source(source,include_non_collinear=False)
			to_metric=Transformer.from_crs(4326,31256,
				always_xy=True).transform
			aoi=transform(to_metric,box(16.348,48.198,16.352,48.202))
			hulls,report=load_turn_use_hulls(source,aoi)
			self.assertEqual(hulls,[])
			self.assertEqual(report["nodes_without_polygonal_hull"],1)

	def test_gpkg_geometry_header_guards(self):
		with self.assertRaisesRegex(ValueError,"GeoPackage"):
			gpkg_geom(b"not a GeoPackage")


if __name__=="__main__":
	unittest.main()
