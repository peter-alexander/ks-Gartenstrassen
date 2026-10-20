"""Offline-Tests für den eigenständigen SIS-Testkachel-Provider."""
import json
import lzma
from pathlib import Path
import sqlite3
import tempfile
import unittest

from pyproj import Transformer
from shapely.geometry import box, mapping, Polygon
from shapely.ops import transform
from shapely.wkt import loads as load_wkt
from shapely.wkb import loads
from shapely.wkb import dumps

from scripts.sis_belagsflaechen import build, read_surfaces


class SISBelagsflaechenTests(unittest.TestCase):
	def setUp(self):
		self.temp = tempfile.TemporaryDirectory()
		self.addCleanup(self.temp.cleanup)
		self.base = Path(self.temp.name)
		to_wgs = Transformer.from_crs("EPSG:31256", "EPSG:4326",
			always_xy=True).transform
		x, y = Transformer.from_crs("EPSG:4326", "EPSG:31256",
			always_xy=True).transform(16.36, 48.22)
		self.polys = [box(x,y,x+20,y+20), box(x+20,y,x+40,y+20)]
		self.doc = {"type": "FeatureCollection", "features": [
			{"type": "Feature", "properties": {"TYPE": kind, "BELAG": belag, "BELAG_TXT": belag_txt},
				"geometry": mapping(transform(to_wgs, poly))}
			for kind, belag, belag_txt, poly in zip(("GG", "EE"), ("GA", "WI"),
			("Gussasphalt Gehsteig", "Wiese"), self.polys)
		]}
		self.source = self.base/"source.json"
		self.source.write_text(json.dumps(self.doc), encoding="utf-8")

	def test_preserves_all_types_and_area_union(self):
		report = build(self.source, self.base/"out")
		self.assertEqual(report["features"], 2)
		self.assertEqual(set(report["type_klassen"]), {"GG","EE"})
		self.assertEqual(set(report["belag_klassen"]), {"GA","WI"})
		self.assertAlmostEqual(report["vereinigte_strassenbelagsflaeche_m2"], 800, delta=.05)
		self.assertAlmostEqual(report["ueberlagerungsflaeche_m2"], 0, delta=.05)
		with sqlite3.connect(self.base/"out"/"sis.sqlite") as db:
			street = loads(db.execute("SELECT geom FROM street").fetchone()[0])
			self.assertAlmostEqual(street.area, 800, delta=.05)
			rows = db.execute("SELECT type,belag FROM surfaces ORDER BY id").fetchall()
			self.assertEqual(rows, [("GG","GA"), ("EE","WI")])
			bbox = db.execute("SELECT minx,maxx,miny,maxy FROM surface_index WHERE id=0").fetchone()
			self.assertAlmostEqual(bbox[0], self.polys[0].bounds[0], delta=.2)
			self.assertAlmostEqual(bbox[1], self.polys[0].bounds[2], delta=.2)
			self.assertAlmostEqual(bbox[2], self.polys[0].bounds[1], delta=.2)
			self.assertAlmostEqual(bbox[3], self.polys[0].bounds[3], delta=.2)
		self.assertEqual((self.base/"out"/"SISBELAGOGD.json").read_bytes(),
			self.source.read_bytes())
		with self.assertRaises(FileExistsError):
			build(self.source, self.base/"out")

	def test_imports_xz_without_uncompressed_copy(self):
		archived = self.base/"cached.geojson.xz"
		archived.write_bytes(lzma.compress(self.source.read_bytes(), preset=6))
		report = build(archived, self.base/"xz-out")
		self.assertEqual(report["features"],2)
		self.assertFalse((self.base/"xz-out"/"SISBELAGOGD.json").exists())
		self.assertEqual(list((self.base/"xz-out").glob("*.geojson")),[])
		with sqlite3.connect(self.base/"xz-out"/"sis.sqlite") as db:
			meta = dict(db.execute("SELECT key,value FROM metadata"))
			self.assertEqual(meta["source_path"],str(archived.resolve()))
			self.assertEqual(meta["provider"],"SISBELAGOGD")

	def test_overlap_fails_without_writing(self):
		doc = json.loads(self.source.read_text(encoding="utf-8"))
		to_wgs = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform
		doc["features"][1]["geometry"] = mapping(transform(to_wgs,
			self.polys[1].translate(-10, 0) if hasattr(self.polys[1], "translate") else box(
				self.polys[1].bounds[0]-10, self.polys[1].bounds[1],
				self.polys[1].bounds[2]-10, self.polys[1].bounds[3])))
		self.source.write_text(json.dumps(doc), encoding="utf-8")
		with self.assertRaisesRegex(ValueError, "überlagern"):
			build(self.source, self.base/"out")
		self.assertFalse((self.base/"out").exists())

	def test_same_ground_class_overlap_is_unioned_once_and_audited(self):
		doc = json.loads(self.source.read_text(encoding="utf-8"))
		doc["features"][1]["properties"].update({
			"BELAG":"GA", "BELAG_TXT":"Gussasphalt Gehsteig"})
		doc["features"][1]["geometry"] = doc["features"][0]["geometry"]
		doc["features"][0].update({"id":"SISBELAGOGD.a"})
		doc["features"][1].update({"id":"SISBELAGOGD.b"})
		doc["features"][0]["properties"]["SIS_ID"] = 1
		doc["features"][1]["properties"]["SIS_ID"] = 2
		self.source.write_text(json.dumps(doc), encoding="utf-8")
		report = build(self.source, self.base/"out")
		self.assertAlmostEqual(report["brutto_summe_m2"], 800, delta=.05)
		self.assertAlmostEqual(report["vereinigte_strassenbelagsflaeche_m2"], 400, delta=.05)
		self.assertAlmostEqual(report["ueberlagerungsflaeche_m2"], 400, delta=.05)
		self.assertEqual(len(report["ueberlagerungspaare"]), 1)
		self.assertTrue(report["ueberlagerungspaare"][0]["gleiche_bodenklasse"])
		self.assertEqual(report["ueberlagerungspaare"][0]["feature_id_a"], "SISBELAGOGD.a")

	def test_invalid_missing_type_rejected_without_output(self):
		doc = json.loads(self.source.read_text(encoding="utf-8"))
		del doc["features"][0]["properties"]["TYPE"]
		self.source.write_text(json.dumps(doc), encoding="utf-8")
		with self.assertRaisesRegex(ValueError, "TYPE"):
			build(self.source, self.base/"out")
		self.assertFalse((self.base/"out").exists())

	def test_explicit_wgs84_crs_accepted(self):
		for name in ("EPSG:4326", "urn:ogc:def:crs:EPSG::4326", "OGC:CRS84"):
			with self.subTest(name=name):
				doc = json.loads(self.source.read_text(encoding="utf-8"))
				doc["crs"] = {"type": "name", "properties": {"name": name}}
				self.source.write_text(json.dumps(doc), encoding="utf-8")
				self.assertEqual(len(read_surfaces(self.source)), 2)

	def test_bad_crs_rejected(self):
		doc = json.loads(self.source.read_text(encoding="utf-8"))
		doc["crs"] = {"type": "name", "properties": {"name": "EPSG:3857"}}
		self.source.write_text(json.dumps(doc), encoding="utf-8")
		with self.assertRaisesRegex(ValueError, "CRS"):
			read_surfaces(self.source)

	def test_degenerate_inner_ring_is_repaired_with_exact_area_audit(self):
		to_wgs = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform
		outer = list(transform(to_wgs, self.polys[0]).exterior.coords)
		point = outer[0]
		invalid = Polygon(outer, [[point, (point[0]+1e-8, point[1]), point, point]])
		self.assertFalse(invalid.is_valid)
		doc = json.loads(self.source.read_text(encoding="utf-8"))
		doc["features"] = [{"type":"Feature", "id":"SISBELAGOGD.test",
			"properties":{"SIS_ID":42,"TYPE":"M1","BELAG":"HS",
				"BELAG_TXT":"Hochbordstein"}, "geometry":mapping(invalid)}]
		self.source.write_text(json.dumps(doc), encoding="utf-8")
		report = build(self.source, self.base/"out")
		self.assertEqual(report["features"], 1)
		self.assertEqual(len(report["geometriekorrekturen"]), 1)
		repair = report["geometriekorrekturen"][0]
		self.assertEqual(repair["feature_id"], "SISBELAGOGD.test")
		self.assertEqual(repair["sis_id"], 42)
		self.assertIn("Too few points", repair["grund"])
		self.assertAlmostEqual(repair["flaechendifferenz_m2"], 0, delta=1e-8)
		self.assertAlmostEqual(repair["symmetrische_differenz_m2"], 0, delta=1e-8)
		with sqlite3.connect(self.base/"out"/"sis.sqlite") as db:
			stored = json.loads(db.execute(
				"SELECT value FROM metadata WHERE key='geometry_repairs'").fetchone()[0])
		self.assertEqual(stored, report["geometriekorrekturen"])

	def test_invalid_polygon_with_area_change_is_not_silently_repaired(self):
		# Selbstkreuzung mit nicht eindeutiger Innenfläche: make_valid darf
		# nicht allein wegen eines plausiblen Ergebnisses übernommen werden.
		to_wgs = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform
		x, y = self.polys[0].bounds[:2]
		bow = Polygon([(x,y),(x+20,y+20),(x,y+20),(x+20,y),(x,y)])
		doc = json.loads(self.source.read_text(encoding="utf-8"))
		doc["features"][0]["geometry"] = mapping(transform(to_wgs, bow))
		self.source.write_text(json.dumps(doc), encoding="utf-8")
		with self.assertRaisesRegex(ValueError, "Reparatur wäre nicht flächentreu|Keine freigegebene konservative Reparatur"):
			build(self.source, self.base/"out")
		self.assertFalse((self.base/"out").exists())

	def test_tiny_self_intersection_is_repaired_only_with_exact_footprint_audit(self):
		# Reale WFS-Form: eine winzige, sich selbst schneidende Spitze. Die
		# metrische Symdiff zum make_valid-Ergebnis muss exakt null bleiben;
		# damit unterscheidet sich der Fall von einer mehrdeutigen Schleife.
		invalid = load_wkt(
			"POLYGON ((16.3039599 48.18973034, 16.30395219 48.18976363, "
			"16.30395159 48.18976354, 16.30394695 48.1897628, "
			"16.30394586 48.18976263, 16.30394621 48.18973969, "
			"16.30394589 48.18973882, 16.3039439 48.18973522, "
			"16.30394282 48.18973385, 16.30394013 48.18973122, "
			"16.30393792 48.18972958, 16.30393587 48.18972832, "
			"16.30393154 48.1897263, 16.30393083 48.18972603, "
			"16.30392737 48.18972496, 16.30392409 48.18972423, "
			"16.30392373 48.18972417, 16.3039599 48.18973034))")
		self.assertFalse(invalid.is_valid)
		doc = json.loads(self.source.read_text(encoding="utf-8"))
		doc["features"] = [{"type": "Feature", "id": "SISBELAGOGD.self-crossing",
			"properties": {"SIS_ID": 3454278, "TYPE": "PA", "BELAG": "GO",
				"BELAG_TXT": "Großsteinpflaster"}, "geometry": mapping(invalid)}]
		self.source.write_text(json.dumps(doc), encoding="utf-8")
		report = build(self.source, self.base/"out")
		repair = report["geometriekorrekturen"][0]
		self.assertIn("Self-intersection", repair["grund"])
		self.assertAlmostEqual(repair["symmetrische_differenz_m2"], 0, delta=1e-10)
		self.assertLess(abs(repair["flaechendifferenz_m2"]), .01)

	def test_tiny_self_intersection_can_use_audited_topology_safe_reference(self):
		# Dieser reale WFS-Fall verhindert eine direkte Symdiff der ungültigen
		# Quelle. make_valid wird nur akzeptiert, wenn die Abweichung zur
		# topologiesicheren Referenz unter derselben 0,01-m²-Grenze bleibt.
		invalid = Polygon([(16.46995095,48.15818239),(16.46995087,48.15818242),
			(16.46994744,48.15818337),(16.46994512,48.15818366),
			(16.46994375,48.1581837),(16.46994007,48.15818338),
			(16.46993903,48.15818317),(16.46993903,48.15818311),
			(16.469944,48.15818365),(16.46994897,48.15818301),
			(16.46995095,48.15818239)])
		# Der synthetische Ring muss tatsächlich selbstschneidend sein.
		self.assertFalse(invalid.is_valid)
		doc = json.loads(self.source.read_text(encoding="utf-8"))
		doc["features"] = [{"type":"Feature", "id":"SISBELAGOGD.buffer-reference",
			"properties":{"SIS_ID":3176924,"TYPE":"FF","BELAG":"AB","BELAG_TXT":"Asphalt"},
			"geometry":mapping(invalid)}]
		self.source.write_text(json.dumps(doc),encoding="utf-8")
		report=build(self.source,self.base/"out")
		self.assertIn("buffer(0)-Referenz",report["geometriekorrekturen"][0]["flaechentreue_nachweis"])

	def test_conflicting_ground_classes_are_rejected(self):
		doc = json.loads(self.source.read_text(encoding="utf-8"))
		doc["features"][1]["geometry"] = doc["features"][0]["geometry"]
		self.source.write_text(json.dumps(doc), encoding="utf-8")
		with self.assertRaisesRegex(ValueError, "widersprüchlich"):
			build(self.source, self.base/"out")
		self.assertFalse((self.base/"out").exists())


if __name__ == "__main__":
	unittest.main()
