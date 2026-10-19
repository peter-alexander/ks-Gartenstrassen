"""Reversible GIP edge grouping before Voronoi, without modifying GIP2."""
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from shapely.geometry import LineString
from shapely.wkb import dumps,loads

from scripts.diagnose_parallel_gip import Axis, find_parallel_pairs
from scripts.merge_parallel_gip import plan_groups, run
from scripts.wienwide_partition import graph_context


def road(gid,y,*,name="Hauptstraße",fow=2,x1=100):
	return Axis(gid,name,fow,gid+"s",gid+"e",
		LineString([(0,y),(x1,y)]))


def synthetic_index(path, edges):
	with sqlite3.connect(path) as db:
		db.executescript("""
			CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
			CREATE TABLE axes(pk INTEGER PRIMARY KEY,gip TEXT UNIQUE NOT NULL,
				name TEXT NOT NULL,fow INTEGER,node_from TEXT NOT NULL,
				node_to TEXT NOT NULL,wkb BLOB NOT NULL);
			CREATE TABLE sites(pk INTEGER PRIMARY KEY,axis_pk INTEGER NOT NULL,
				x REAL NOT NULL,y REAL NOT NULL);
			CREATE VIRTUAL TABLE site_spatial USING rtree(pk,minx,maxx,miny,maxy);
			CREATE INDEX sites_by_axis ON sites(axis_pk);
			CREATE TABLE nodes(pk INTEGER PRIMARY KEY,gip TEXT,name TEXT,
				x REAL,y REAL,wkb BLOB);
			CREATE VIRTUAL TABLE node_spatial USING rtree(pk,minx,maxx,miny,maxy);
			CREATE TABLE node_degrees(gip TEXT PRIMARY KEY,degree INTEGER);
		""")
		for key,value in (("crs","EPSG:31256"),
				("index_method","gip2-local-edge-turn-use-v1"),
				("sampling_m",5),("max_axis_distance_m",25),
				("achsen",len(edges)),("voronoi_sites",len(edges))):
			db.execute("INSERT INTO meta VALUES (?,?)",(key,json.dumps(value)))
		for a in edges:
			cur=db.execute("INSERT INTO axes(gip,name,fow,node_from,node_to,wkb)"
				" VALUES (?,?,?,?,?,?)",
				(a.id,a.name,a.fow,a.start,a.end,dumps(a.geom)))
			center=a.geom.interpolate(a.geom.length/2)
			site=db.execute("INSERT INTO sites(axis_pk,x,y) VALUES (?,?,?)",
				(cur.lastrowid,center.x,center.y))
			db.execute("INSERT INTO site_spatial VALUES (?,?,?,?,?)",
				(site.lastrowid,center.x,center.x,center.y,center.y))


class GroupingTests(unittest.TestCase):
	def test_reversible_grouped_index_preserves_original_sites_and_geometry(self):
		edges=[road("a",0),road("b",15),road("c",7,fow=505,name="Radweg"),
			road("d",500)]
		with TemporaryDirectory() as folder:
			root=Path(folder)
			source=root/"gip.sqlite"
			out=root/"gip_merged.sqlite"
			synthetic_index(source,edges)
			source_bytes=source.read_bytes()
			result=run(source,out)
			self.assertEqual(source.read_bytes(),source_bytes)
			self.assertEqual(result["merged_groups"],1)
			self.assertEqual(result["original_axes"],4)
			self.assertEqual(result["achsen"],2)
			self.assertEqual(result["voronoi_sites"],4)
			with sqlite3.connect(out) as db:
				self.assertEqual(dict(db.execute(
					"SELECT original_id,representative_id FROM merged_members")),
					{"a":"a","b":"a","c":"a","d":"d"})
				self.assertEqual(dict(db.execute(
					"SELECT gip,fow FROM axes")),{"a":2,"d":2})
				self.assertEqual(dict(db.execute(
					"SELECT pk,gip FROM axes"))[1],"a")
				self.assertEqual(db.execute(
					"SELECT COUNT(*) FROM sites").fetchone()[0],4)
				self.assertEqual(db.execute(
					"SELECT COUNT(*) FROM sites WHERE axis_pk=1").fetchone()[0],3)
				self.assertEqual(loads(db.execute(
					"SELECT wkb FROM axes WHERE gip='a'").fetchone()[0]).geom_type,
					"MultiLineString")
				db.row_factory=sqlite3.Row
				sites,axes,nodes=graph_context(db,(0,-30,100,30),halo=75)
				self.assertEqual(len(sites),3)
				self.assertEqual(set(axes),{1})
				self.assertFalse(nodes)
			self.assertEqual(run(source,out,reuse=True)["original_axes"],4)
			with self.assertRaises(FileExistsError):
				run(source,out)

	def test_no_blind_transitive_chain(self):
		axes=[road("a",0),road("b",15),road("c",30)]
		pairs,_=find_parallel_pairs(axes)
		groups,_=plan_groups(axes,pairs)
		self.assertEqual(groups,{"a":("a","b")})
		self.assertNotIn("c",next(iter(groups.values())))

	def test_ambiguous_support_remains_unmerged(self):
		axes=[road("a",0,name="Allee"),road("b",15,name="Gasse"),
			road("c",7,fow=505,name="Radweg")]
		pairs,_=find_parallel_pairs(axes)
		groups,audit=plan_groups(axes,pairs)
		self.assertEqual(groups,{})
		self.assertEqual(audit["ambiguous_support"],1)

	def test_pedestrian_area_not_merged_into_road(self):
		axes=[road("a",0,fow=14),road("b",10,fow=3)]
		pairs,_=find_parallel_pairs(axes)
		groups,_=plan_groups(axes,pairs)
		self.assertFalse(groups)


if __name__=="__main__":
	unittest.main()
