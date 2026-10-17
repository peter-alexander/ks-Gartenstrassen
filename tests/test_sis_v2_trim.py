"""Integrationsprüfung: nachträgliches Voronoi-Kürzen mit geschlossener Bilanz."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from shapely.geometry import LineString, Polygon
from shapely.wkb import dumps, loads

from scripts.sis_v2_trim import run


class VoronoiTrimTests(unittest.TestCase):
	def test_wedge_is_cut_and_area_moves_to_junction(self):
		with tempfile.TemporaryDirectory() as folder:
			root = Path(folder)
			gip = root / "gip.sqlite"
			raw = root / "raw.sqlite"
			out = root / "result.sqlite"
			axis = LineString([(0, 0), (40, 0)])
			wedge = Polygon([
				(0, 0), (10, -5), (40, -5), (40, 5), (10, 5)])
			with sqlite3.connect(gip) as db:
				db.execute("CREATE TABLE meta(key TEXT,value TEXT)")
				db.execute("INSERT INTO meta VALUES (?,?)",
					("index_method", json.dumps("gip2-local-edge-turn-use-v1")))
				db.execute("CREATE TABLE axes(gip TEXT,wkb BLOB)")
				db.execute("INSERT INTO axes VALUES (?,?)", ("edge", dumps(axis)))
			with sqlite3.connect(raw) as db:
				db.execute("CREATE TABLE config(key TEXT,value TEXT)")
				db.executemany("INSERT INTO config VALUES (?,?)", [
					("junction_policy", "none"), ("fow_policy", "all")])
				db.execute("CREATE TABLE tiles(id TEXT,street_sha256 TEXT,"
					"area REAL,assigned REAL,unresolved REAL,elapsed_s REAL,stats_json TEXT)")
				db.execute("CREATE TABLE parts(tile_id TEXT,kind TEXT,gip_id TEXT,"
					"area REAL,geom BLOB,PRIMARY KEY(tile_id,kind,gip_id))")
				db.execute("INSERT INTO tiles VALUES (?,?,?,?,?,?,?)",
					("tile","hash",wedge.area,wedge.area,0.,0.,
						json.dumps({"strassenraum_m2":wedge.area,
							"zugeordnet_m2":wedge.area,"ungeklaert_m2":0.})))
				db.execute("INSERT INTO parts VALUES (?,?,?,?,?)",
					("tile","abschnitt","edge",wedge.area,dumps(wedge)))
			result = run(gip,raw,out)
			self.assertGreater(result["geschnittene_flaeche_m2"], 1)
			with sqlite3.connect(out) as db:
				pieces = {(k,g):loads(blob) for k,g,blob in db.execute(
					"SELECT kind,gip_id,geom FROM parts")}
				kept = pieces["abschnitt","edge"]
				removed = pieces["ungeklaert","knotenbereich"]
				self.assertTrue(kept.is_valid)
				self.assertTrue(removed.is_valid)
				self.assertAlmostEqual(kept.area + removed.area, wedge.area, places=6)
				self.assertAlmostEqual(kept.intersection(removed).area,0,places=6)
				self.assertAlmostEqual(kept.union(removed).symmetric_difference(wedge).area,0,places=6)
				assigned,unresolved = db.execute(
					"SELECT assigned,unresolved FROM tiles").fetchone()
				self.assertAlmostEqual(assigned,kept.area,places=6)
				self.assertAlmostEqual(unresolved,removed.area,places=6)
				self.assertEqual(dict(db.execute(
					"SELECT key,value FROM config"))["junction_policy"],
					"voronoi-stable-width-v1")
			with sqlite3.connect(raw) as db:
				self.assertAlmostEqual(db.execute(
					"SELECT area FROM parts").fetchone()[0],wedge.area)
