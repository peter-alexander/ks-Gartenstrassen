"""Cache validation must reject old GIP assignments and preserve cached files."""
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pyproj import Transformer
from shapely.geometry import box, mapping
from shapely.ops import transform

from scripts.verify_wien_cache import verify
from scripts.sis_v2_cross_sections import STEP_M, WINDOW, TOLERANCE, MIN_GROWTH, MAX_SEARCH_M
from scripts.wienwide_grid import build_manifest, write_manifest, checksum


class CachedViennaDataTests(unittest.TestCase):
	def setUp(self):
		self.dir=TemporaryDirectory()
		self.addCleanup(self.dir.cleanup)
		self.root=Path(self.dir.name)
		self.cached=self.root/"cache"/"wien"
		self.cached.mkdir(parents=True)
		to_wgs=Transformer.from_crs("EPSG:31256","EPSG:4326",
			always_xy=True).transform
		geom=transform(to_wgs,box(0,0,15,15))
		(self.cached/"aoi.geojson").write_text(json.dumps(mapping(geom)))
		self.manifest=self.cached/"raster.json"
		write_manifest(self.manifest,build_manifest(
			self.cached/"aoi.geojson",size=1000,halo=75))
		self.merged=self.cached/"gip_merged.sqlite"
		with sqlite3.connect(self.merged) as db:
			db.execute("CREATE TABLE meta(key TEXT,value TEXT)")
		self.graph_sha=checksum(self.merged)
		self.manifest_sha=checksum(self.manifest)

	def _partition(self,name,*,gid_sha=None,final=False):
		path=self.cached/name
		with sqlite3.connect(path) as db:
			db.execute("CREATE TABLE config(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
			db.execute("CREATE TABLE tiles(id TEXT PRIMARY KEY)")
			fields={
				"manifest_sha256":self.manifest_sha,
				"gip_sha256":gid_sha or self.graph_sha,
				"schema_version":"1",
				"junction_policy":"voronoi-stable-width-v1" if final else "none",
				"fow_policy":"all",
			}
			if final:
				fields["querschnitt_regel"]=json.dumps({
					"step_m":STEP_M,"fenster":WINDOW,"toleranz":TOLERANCE,
					"mindestzunahme":MIN_GROWTH,"suchweite_m":MAX_SEARCH_M})
			db.executemany("INSERT INTO config VALUES (?,?)",fields.items())
			db.execute("INSERT INTO tiles VALUES (?)",(
				json.loads(self.manifest.read_text())["tiles"][0]["id"],))
		return path

	def test_grid_validation_uses_copied_cache_aoi(self):
		self.assertEqual(verify("grid",self.cached)["tiles"],1)
		with self.assertRaisesRegex(ValueError,"Kachelgröße"):
			verify("grid",self.cached,tile_m=250)

	def test_legacy_partition_is_rejected_without_rewriting_it(self):
		raw=self._partition("aufteilung_roh.sqlite",gid_sha="old-unmerged-gip")
		before=raw.read_bytes()
		self._partition("aufteilung.sqlite",final=True)
		with self.assertRaisesRegex(ValueError,"aktuellen GIP"):
			verify("trim",self.cached)
		self.assertEqual(raw.read_bytes(),before)

	def test_new_partition_and_qa_can_be_verified(self):
		self._partition("aufteilung_roh.sqlite")
		final=self._partition("aufteilung.sqlite",final=True)
		self.assertEqual(verify("trim",self.cached)["graph_sha256"],self.graph_sha)
		qa=self.cached/"qa.gpkg"
		with sqlite3.connect(qa) as db:
			db.execute("CREATE TABLE qa_provenienz(key TEXT,value TEXT)")
			db.executemany("INSERT INTO qa_provenienz VALUES (?,?)",(
				(k,json.dumps(v)) for k,v in {
					"manifest_sha256":self.manifest_sha,
					"gip_sha256":self.graph_sha,
					"partition_sha256":checksum(final),
					"kacheln":1,"schema_version":1,
				}.items()))
		self.assertEqual(verify("qa",self.cached)["tiles"],1)
		with sqlite3.connect(qa) as db:
			db.execute("UPDATE qa_provenienz SET value=? WHERE key='partition_sha256'",
				(json.dumps("other"),))
		with self.assertRaisesRegex(ValueError,"anderen"):
			verify("qa",self.cached)


if __name__=="__main__":
	unittest.main()
