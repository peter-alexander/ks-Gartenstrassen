"""Original LINEAR_USE: source geometries must reach CGAL unchanged."""
import json
import sqlite3
import struct
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pyproj import Transformer
from shapely.geometry import LineString, box, mapping
from shapely.ops import transform
from shapely.wkb import dumps, loads

from scripts.build_linear_use_original import build


def gpkg_blob(geometry,srs_id=4326):
	return b"GP"+bytes((0,1))+struct.pack("<i",srs_id)+dumps(geometry)


class LinearUseOriginalImportTests(unittest.TestCase):
	def setUp(self):
		self.tmp=TemporaryDirectory()
		self.addCleanup(self.tmp.cleanup)
		self.root=Path(self.tmp.name)
		self.source=self.root/"gip_network_ogd.gpkg"
		self.aoi=self.root/"wien.geojson"
		self.cache=self.root/"linear_use.sqlite"
		self.geojson=self.root/"linear_use_original.geojson"
		to_metric=Transformer.from_crs("EPSG:4326","EPSG:31256",
			always_xy=True).transform
		to_wgs=Transformer.from_crs("EPSG:31256","EPSG:4326",
			always_xy=True).transform
		x,y=to_metric(16.36,48.22)
		self.metric_origin=(x,y)
		aoi_metric=box(x-50,y-50,x+250,y+100)
		self.aoi.write_text(json.dumps(mapping(transform(to_wgs,aoi_metric))),
			encoding="utf-8")
		with sqlite3.connect(self.source) as db:
			db.executescript("""
				CREATE TABLE gpkg_spatial_ref_sys(
					srs_name TEXT NOT NULL,
					srs_id INTEGER NOT NULL PRIMARY KEY,
					organization TEXT NOT NULL,
					organization_coordsys_id INTEGER NOT NULL,
					definition TEXT NOT NULL,
					description TEXT
				);
				INSERT INTO gpkg_spatial_ref_sys VALUES
					('WGS 84',4326,'EPSG',4326,'undefined','');
				CREATE TABLE gpkg_geometry_columns(
					table_name TEXT NOT NULL,
					column_name TEXT NOT NULL,
					geometry_type_name TEXT NOT NULL,
					srs_id INTEGER NOT NULL,
					z TINYINT NOT NULL,
					m TINYINT NOT NULL
				);
				CREATE TABLE LINEAR_USE(
					fid INTEGER PRIMARY KEY,
					object_id TEXT NOT NULL,
					edge_id TEXT NOT NULL,
					edge_percentage_from REAL,
					edge_percentage_to REAL,
					base_type INTEGER NOT NULL,
					length_m REAL,
					feature_name TEXT,
					geom BLOB NOT NULL
				);
				INSERT INTO gpkg_geometry_columns VALUES
					('LINEAR_USE','geom','LINESTRING',4326,0,0);
				CREATE VIRTUAL TABLE rtree_LINEAR_USE_geom
					USING rtree(id,minx,maxx,miny,maxy);
			""")
			def add(fid,object_id,edge_id,line_metric,*,base_type=1,name="Fahrbahn"):
				line=transform(to_wgs,line_metric)
				cur=db.execute("""INSERT INTO LINEAR_USE
					(fid,object_id,edge_id,edge_percentage_from,
					 edge_percentage_to,base_type,length_m,feature_name,geom)
					VALUES (?,?,?,?,?,?,?,?,?)""",
					(fid,object_id,edge_id,0,100,base_type,
						line_metric.length,name,gpkg_blob(line)))
				minx,miny,maxx,maxy=line.bounds
				db.execute("INSERT INTO rtree_LINEAR_USE_geom VALUES (?,?,?,?,?)",
					(fid,minx,maxx,miny,maxy))
			add(1,"lu-a1","edge-a",
				LineString([(x,y),(x+100,y)]),name="Fahrbahn Teststraße")
			add(2,"lu-a2","edge-a",
				LineString([(x,y+10),(x+100,y+10)]),
				name="Fahrbahn Teststraße")
			add(3,"lu-b1","edge-b",
				LineString([(x,y+30),(x+120,y+30)]),
				name="Fahrbahn Nebenstraße")
			add(4,"lu-radweg","edge-radweg",
				LineString([(x,y+40),(x+100,y+40)]),base_type=2)
			add(6,"lu-ignore-type","edge-ignore-type",
				LineString([(x,y+40),(x+100,y+40)]),base_type=4)
			add(5,"lu-outside","edge-outside",
				LineString([(x+10000,y),(x+10100,y)]))

	def test_original_lines_not_averaged(self):
		report=build(self.source,self.aoi,self.cache,self.geojson)
		self.assertEqual(report["original_lines"],4)
		self.assertEqual(report["edge_ids"],3)
		self.assertEqual(report["spatial_prefilter"],"gpkg_rtree")
		with sqlite3.connect(self.cache) as db:
			metadata={k:json.loads(v) for k,v in
				db.execute("SELECT key,value FROM metadata")}
			self.assertEqual(metadata["schema"],"linear-use-original-segments-v2")
			self.assertEqual(metadata["base_types"],[1,2,6,7,8,9,33,34,35,36,51])
			rows=db.execute("SELECT object_id,edge_id,wkb FROM linear_use_segments ORDER BY object_id").fetchall()
		self.assertEqual([row[0] for row in rows],["lu-a1","lu-a2","lu-b1","lu-radweg"])
		self.assertEqual([row[1] for row in rows],["edge-a","edge-a","edge-b","edge-radweg"])
		y=[loads(row[2]).coords[0][1] for row in rows]
		self.assertAlmostEqual(y[0],self.metric_origin[1],delta=.05)
		self.assertAlmostEqual(y[1],self.metric_origin[1]+10,delta=.05)
		self.assertAlmostEqual(y[2],self.metric_origin[1]+30,delta=.05)
		doc=json.loads(self.geojson.read_text(encoding="utf-8"))
		self.assertEqual(len(doc["features"]),4)
		self.assertEqual([f["properties"]["object_id"] for f in doc["features"]],
			["lu-a1","lu-a2","lu-b1"])

	def test_source_is_read_only_and_outputs_not_overwritten(self):
		before=self.source.read_bytes()
		build(self.source,self.aoi,self.cache,self.geojson)
		self.assertEqual(self.source.read_bytes(),before)
		with self.assertRaises(FileExistsError):
			build(self.source,self.aoi,self.cache,self.geojson)
		self.assertEqual(self.source.read_bytes(),before)

	def test_missing_edge_id_fails_without_partial_outputs(self):
		with sqlite3.connect(self.source) as db:
			db.execute("UPDATE LINEAR_USE SET edge_id='' WHERE object_id='lu-b1'")
		with self.assertRaisesRegex(ValueError,"edge_id"):
			build(self.source,self.aoi,self.cache,self.geojson)
		self.assertFalse(self.cache.exists())
		self.assertFalse(self.geojson.exists())


if __name__=="__main__":
	unittest.main()
