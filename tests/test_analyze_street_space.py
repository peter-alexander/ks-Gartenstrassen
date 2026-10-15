import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest

from shapely import to_wkb
from shapely.geometry import Polygon, box

from scripts.analyze_street_space import (
	analyze, build_review, classify_contact, load_polygons,
)
from scripts.extract_fmzk import DEFAULT_BBOX, parse_bbox, projected_clip


def make_gpkg(folder, records):
	path = folder / "fmzk_test.gpkg"
	with sqlite3.connect(path) as conn:
		conn.executescript("""
			CREATE TABLE gpkg_contents (table_name TEXT, srs_id INTEGER);
			CREATE TABLE gpkg_geometry_columns (table_name TEXT, column_name TEXT, srs_id INTEGER);
			INSERT INTO gpkg_contents VALUES ('fmzk', 31256);
			INSERT INTO gpkg_geometry_columns VALUES ('fmzk', 'geom', 31256);
			CREATE TABLE fmzk (
				id INTEGER PRIMARY KEY, geom BLOB, F_KLASSE INTEGER,
				F_KLASSE_TEXT TEXT, FMZK_ID INTEGER
			);
		""")
		for fid, code, geom in records:
			blob = b"GP" + bytes((0, 1)) + struct.pack("<i", 31256) + to_wkb(geom)
			conn.execute(
				"INSERT INTO fmzk VALUES (?, ?, ?, ?, ?)",
				(fid, blob, code, f"Klasse {code}", fid),
			)
	path.with_suffix(".json").write_text(json.dumps({
		"output_layer": "fmzk",
		"output_srs": "EPSG:31256",
		"bbox_lon_lat": list(parse_bbox(DEFAULT_BBOX)),
		"feature_count": len(records),
	}), encoding="utf-8")
	return path


class StreetSpaceTest(unittest.TestCase):
	def setUp(self):
		point = projected_clip(parse_bbox(DEFAULT_BBOX)).centroid
		self.x, self.y = point.x, point.y

	def rectangle(self, left, bottom, right, top):
		return box(self.x + left, self.y + bottom, self.x + right, self.y + top)

	def sample_features(self):
		return [
			(1, 21, "Fahrbahn", self.rectangle(-20, -2, 20, 2)),
			(2, 23, "Gehsteig", self.rectangle(-20, -4, 20, -2)),
			(3, 58, "Grünfläche", self.rectangle(-5, 2, 5, 5)),
			(4, 69, "Sonstige Grünfläche", self.rectangle(10, 3.2, 15, 5.2)),
			(5, 58, "Grünfläche", self.rectangle(-5, 30, 5, 35)),
			(6, 59, "Befestigte Fläche", self.rectangle(-10, -7, -5, -4)),
			(7, 51, "Innenhof", self.rectangle(6, 5, 12, 9)),
			(8, 25, "Gehweg, Radweg", self.rectangle(6, 10, 12, 12)),
			(9, 11, "Gebäude", self.rectangle(6, 13, 12, 20)),
			(10, 39, "Sonstige Verkehrsfläche", self.rectangle(20, -2, 24, 2)),
		]

	def test_green_nearby_is_only_candidate_not_confirmed_street(self):
		review = build_review(self.sample_features())
		self.assertEqual(round(review["core"].area, 4), 268.0)
		items = {c["id"]: c for c in review["candidates"]}
		self.assertEqual(items[3]["status"], "grenzt_an_kern")
		self.assertAlmostEqual(items[3]["abstand_kern_m"], 0)
		self.assertGreater(items[3]["randkontakt_m"], 9)
		self.assertEqual(items[4]["status"], "nahe_kern")
		self.assertEqual(items[5]["status"], "fern_vom_kern")
		self.assertEqual(items[6]["status"], "grenzt_an_kern")
		self.assertEqual(items[6]["rolle"], "unklar_pruefen")
		self.assertNotIn(7, items)
		self.assertNotIn(8, items)
		self.assertNotIn(10, items)
		self.assertEqual(next(props for props, geom in review["features"] if props["id"] == 10)["rolle"], "kern")
		self.assertEqual(next(props for props, geom in review["features"] if props["id"] == 8)["rolle"], "kern")
		self.assertNotIn(9, [props["id"] for props, geom in review["features"]])
		self.assertEqual(next(props for props, geom in review["features"] if props["id"] == 7)["rolle"], "privat_kontext")

	def test_class_39_alone_can_form_core(self):
		pieces = [
			(1, 39, "Sonstige Verkehrsfläche", self.rectangle(-5, -5, 5, 5)),
			(2, 69, "Sonstige Grünfläche", self.rectangle(5, -5, 7, 5)),
		]
		review = build_review(pieces)
		self.assertAlmostEqual(review["core"].area, 100)
		self.assertEqual(len(review["candidates"]), 1)
		self.assertEqual(review["candidates"][0]["id"], 2)
		self.assertEqual(review["candidates"][0]["status"], "grenzt_an_kern")

	def test_corner_contact_is_not_a_proven_shared_street_edge(self):
		core = self.rectangle(-20, -2, 20, 2)
		corner = self.rectangle(20, 2, 24, 6)
		info = classify_contact(corner, core, core.boundary.buffer(.25),
			core.buffer(2), near_m=2, min_contact_m=1)
		self.assertEqual(info["status"], "nahe_kern")
		self.assertEqual(info["abstand_kern_m"], 0)
		self.assertLess(info["randkontakt_m"], 1)

	def test_large_garden_near_sidewalk_is_not_whole_street_space(self):
		core = self.rectangle(-20, -2, 20, 2)
		garden = self.rectangle(-10, 2, 10, 60)
		info = classify_contact(garden, core, core.boundary.buffer(.25),
			core.buffer(2), near_m=2, min_contact_m=.5)
		self.assertEqual(info["status"], "grenzt_an_kern")
		self.assertLess(info["flaeche_im_umfeld_pct"], 5)

	def test_end_to_end_local_files_and_wgs84_output(self):
		with tempfile.TemporaryDirectory() as tmp:
			folder = Path(tmp)
			records = [(fid, code, geom) for fid, code, _, geom in self.sample_features()]
			path = make_gpkg(folder, records)
			report = analyze(path, folder / "review")
			self.assertEqual(report["features_gesamt"], len(records))
			self.assertEqual(report["kern_klassen"], [21, 23, 24, 25, 33, 39])
			self.assertAlmostEqual(report["kern_union_m2"], 268)
			self.assertTrue(report["kandidaten_flächen_sind_keine_bestätigten_strassenflächen"])
			self.assertTrue((folder / "review" / "strassenraum_kandidaten.csv").exists())
			review = json.loads((folder / "review" / "strassenraum_pruefung.geojson").read_text())
			ids = {f["properties"]["id"] for f in review["features"]}
			candidate = next(f["properties"] for f in review["features"] if f["properties"]["id"] == 3)
			self.assertIn("einbettung", candidate)
			self.assertIn("kontakt_21_m", candidate)
			self.assertIn("richtung_ungeklaert_m", candidate)
			self.assertIn("kandidaten_je_klasse_und_einbettung", report)
			self.assertGreater(sum(x["objekte"] for x in report["kandidaten_je_klasse_und_einbettung"]), 0)
			self.assertIn(7, ids)
			self.assertNotIn(9, ids)
			core_json = json.loads((folder / "review" / "strassenraum_kern.geojson").read_text())
			coord = core_json["features"][0]["geometry"]["coordinates"]
			def flatten(value):
				if isinstance(value, (float, int)):
					yield value
				else:
					for child in value:
						yield from flatten(child)
			numbers = list(flatten(coord))
			self.assertTrue(any(16 < v < 17 for v in numbers))
			self.assertTrue(any(48 < v < 49 for v in numbers))
			self.assertTrue(path.exists())

	def test_small_positive_polygon_area_is_not_rounded_to_zero(self):
		# FMZK-Auszüge können winzige, aber gültige Flächen enthalten.
		features = [
			(1, 21, "Fahrbahn", self.rectangle(-5, -5, 5, 5)),
			(2, 69, "Sonstige Grünfläche", self.rectangle(5, 0, 5.001, 0.001)),
		]
		review = build_review(features)
		area = next(f["flaeche_m2"] for f in review["candidates"] if f["id"] == 2)
		self.assertGreater(area, 0)
		self.assertLess(area, .005)
		self.assertAlmostEqual(area, 0.000001, delta=1e-9)
		prop = next(props for props, _ in review["features"] if props["id"] == 2)
		self.assertEqual(prop["flaeche_m2"], area)

	def test_validation_missing_core_and_manifest_counts(self):
		with self.assertRaisesRegex(ValueError, "Keine Kernflächen"):
			build_review([(1, 58, "Grünfläche", self.rectangle(0, 0, 10, 10))])
		with self.assertRaises(ValueError):
			build_review(self.sample_features(), near_m=-1)
		with tempfile.TemporaryDirectory() as tmp:
			folder = Path(tmp)
			path = make_gpkg(folder, [(1, 21, self.rectangle(-5, -5, 5, 5))])
			m = path.with_suffix(".json")
			data = json.loads(m.read_text())
			data["feature_count"] = 2
			m.write_text(json.dumps(data))
			with self.assertRaisesRegex(ValueError, "Feature-Anzahl"):
				load_polygons(path)

	def test_invalid_source_polygon_repairs_logged(self):
		bowtie = Polygon([
			(self.x - 5, self.y - 5), (self.x + 5, self.y + 5),
			(self.x - 5, self.y + 5), (self.x + 5, self.y - 5),
		])
		with tempfile.TemporaryDirectory() as tmp:
			folder = Path(tmp)
			path = make_gpkg(folder, [
				(1, 21, self.rectangle(-20, -2, 20, 2)),
				(2, 58, bowtie),
			])
			_, _, _, repairs = load_polygons(path)
			self.assertEqual(len(repairs), 1)
			self.assertEqual(repairs[0]["id"], 2)


if __name__ == "__main__":
	unittest.main()
