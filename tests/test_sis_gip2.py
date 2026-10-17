"""Lokale GIP-2.0-Adaptertests ohne vollständigen österreichischen GIP-Datensatz."""
import sqlite3
import json
from pathlib import Path
import tempfile
import struct
import unittest

from shapely.geometry import LineString, MultiPoint, Point, box, mapping
from shapely.wkb import dumps, loads
from shapely.ops import transform
from pyproj import Transformer
from scripts.wienwide_grid import build_manifest, write_manifest

from scripts.sis_gip2 import gpkg_geom, build


def gpkg(geometry, envelope=0):
	# GeoPackage WKB header: GP / version 0 / flags little-endian / EPSG 4326.
	flag = 1 | (envelope << 1)
	extras = b"\x00" * (0, 32, 48, 48, 64)[envelope]
	return b"GP" + bytes((0,flag)) + struct.pack("<i",4326) + extras + dumps(geometry)


class GIP2GeometryTests(unittest.TestCase):
	def test_gpkg_geometry_without_envelope(self):
		g = Point(16.3627,48.1907)
		self.assertTrue(gpkg_geom(gpkg(g)).equals(g))

	def test_gpkg_geometry_with_xy_envelope(self):
		g = LineString([(16.36,48.19),(16.37,48.20)])
		self.assertTrue(gpkg_geom(gpkg(g,1)).equals(g))

	def test_invalid_gpkg_header(self):
		with self.assertRaisesRegex(ValueError,"GeoPackage"):
			gpkg_geom(b"not gpkg")

	def test_convex_hull_ignores_interior_points(self):
		points = [(0,0),(3,0),(3,2),(0,2),(1,1),(2,1)]
		hull = MultiPoint(points).convex_hull
		self.assertEqual(hull.geom_type,"Polygon")
		self.assertAlmostEqual(hull.area,6.)

	def test_degenerate_hull_is_not_polygon(self):
		self.assertEqual(MultiPoint([(0,0),(1,0),(2,0)]).convex_hull.geom_type,
			"LineString")

	def test_build_local_gip2_node_turnuse_edge_index(self):
		with tempfile.TemporaryDirectory() as folder:
			root = Path(folder)
			to_wgs = Transformer.from_crs("EPSG:31256","EPSG:4326",
				always_xy=True).transform
			from_wgs = Transformer.from_crs("EPSG:4326","EPSG:31256",
				always_xy=True).transform
			x,y = from_wgs(16.36,48.20)
			aoi = root/"aoi.geojson"
			aoi.write_text(json.dumps(mapping(transform(to_wgs,
				box(x-60,y-60,x+60,y+60)))))
			manifest = root/"manifest.json"
			write_manifest(manifest, build_manifest(aoi,size=250,halo=75))
			source = root/"gip.gpkg"
			with sqlite3.connect(source) as db:
				db.execute("CREATE TABLE gpkg_contents(table_name TEXT)")
				for layer, columns in (
					("EDGE","object_id TEXT,node_from_id TEXT,node_to_id TEXT,mainname_text TEXT,feature_name TEXT,form_of_way INTEGER"),
					("NODE","object_id TEXT,feature_name TEXT,edge_degree INTEGER"),
					("TURN_USE","object_id TEXT,via_node_id TEXT")):
					db.execute(f"CREATE TABLE {layer}(fid INTEGER PRIMARY KEY,geom BLOB,{columns})")
					db.execute("INSERT INTO gpkg_contents VALUES (?)",(layer,))
					db.execute(f"CREATE VIRTUAL TABLE rtree_{layer}_geom USING rtree(id,minx,maxx,miny,maxy)")
				def add(layer, geom, columns):
					g = transform(to_wgs,geom)
					query = ",".join("?" for _ in range(len(columns)+1))
					cur=db.execute(f"INSERT INTO {layer}(geom,{','.join(columns)}) VALUES ({query})",
						(gpkg(g),*columns.values()))
					b=g.bounds
					db.execute(f"INSERT INTO rtree_{layer}_geom VALUES (?,?,?,?,?)",
						(cur.lastrowid,b[0],b[2],b[1],b[3]))
				add("EDGE",LineString([(x-70,y),(x+70,y)]),
					{"object_id":"edge-one","node_from_id":"left",
					"node_to_id":"right","mainname_text":"Test","feature_name":"Test","form_of_way":1})
				add("EDGE",LineString([(x,y-70),(x,y+70)]),
					{"object_id":"edge-two","node_from_id":"bottom",
					"node_to_id":"top","mainname_text":"Test","feature_name":"Test","form_of_way":3})
				add("NODE",Point(x,y),
					{"object_id":"node-one","feature_name":"Kreuzung","edge_degree":4})
				add("TURN_USE",LineString([(x-10,y-5),(x+10,y-5)]),
					{"object_id":"turn-one","via_node_id":"node-one"})
				add("TURN_USE",LineString([(x+10,y+5),(x-10,y+5)]),
					{"object_id":"turn-two","via_node_id":"node-one"})
			target = root/"index.sqlite"
			report = build(source,manifest,target)
			self.assertEqual(report["achsen"],2)
			self.assertGreater(report["voronoi_sites"],2)
			self.assertEqual(report["knoten"],1)
			self.assertEqual(report["kreuzungshuelle"],1)
			with sqlite3.connect(target) as db:
				area = db.execute("SELECT area_m2 FROM junctions").fetchone()[0]
				self.assertAlmostEqual(area,200,delta=.05)
				self.assertEqual(db.execute("SELECT COUNT(*) FROM axes").fetchone()[0],2)


if __name__=="__main__":
	unittest.main()
