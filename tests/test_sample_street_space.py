import csv
import json
from pathlib import Path
import random
import sqlite3
import tempfile
import unittest

from shapely.geometry import box, mapping, shape

from scripts.sample_street_space import (
	choose_diverse, create_sample, lookup_original_ids, read_review, sample_groups,
)


def synthetic_features():
	features = []
	fid = 10
	groups = [
		(69, "mehrseitig_verschiedene_klassen", "grenzt_an_kern", 9),
		(69, "mehrseitig", "grenzt_an_kern", 8),
		(69, "einseitig", "grenzt_an_kern", 5),
		(69, "kein_deutlicher_randkontakt", "fern_vom_kern", 7),
		(58, "einseitig", "grenzt_an_kern", 7),
		(59, "mehrseitig", "grenzt_an_kern", 3),
		(59, "mehrseitig_verschiedene_klassen", "grenzt_an_kern", 5),
	]
	for code, embedding, status, amount in groups:
		for n in range(amount):
			fid += 1
			size = 0.000003 * (n + 1)
			x, y = 16.362 + (fid % 9) * 0.00027, 48.2215 + (fid // 9) * 0.00027
			features.append({"type": "Feature", "properties": {
				"id": fid, "f_klasse": code, "f_klasse_text": f"Klasse {code}",
				"flaeche_m2": float(n + 1), "einbettung": embedding,
				"status": status, "abstand_kern_m": 0, "kontaktklassen": "21,23",
			}, "geometry": mapping(box(x, y, x + size, y + size))})
	return features


def local_fixture(folder, features):
	review = folder / "strassenraum_pruefung.geojson"
	review.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
	source = folder / "fmzk_test.gpkg"
	with sqlite3.connect(source) as conn:
		conn.execute('CREATE TABLE fmzk (id INTEGER PRIMARY KEY, F_KLASSE INTEGER, FMZK_ID INTEGER, KLASSE_SUB INTEGER, KLASSE_SUB_TEXT TEXT, BEZUG TEXT)')
		for feature in features:
			prop = feature["properties"]
			conn.execute('INSERT INTO fmzk VALUES (?, ?, ?, ?, ?, ?)',
				(prop["id"], prop["f_klasse"], prop["id"] + 10000, 12, "Beispiel", "2026"))
	return review, source


class SampleStreetSpaceTest(unittest.TestCase):
	def setUp(self):
		self.features = synthetic_features()

	def test_group_quotas_and_id_uniqueness(self):
		picks, counts = sample_groups(self.features)
		self.assertEqual(len(picks), 25)
		self.assertEqual([count["ausgewaehlt"] for count in counts], [5, 5, 3, 3, 5, 4])
		self.assertEqual(len({feature["properties"]["id"] for _, feature in picks}), 25)
		self.assertEqual({feature["properties"]["einbettung"] for group, feature in picks
			if group == "59_mehrseitig"}, {"mehrseitig", "mehrseitig_verschiedene_klassen"})
		self.assertEqual({feature["properties"]["status"] for group, feature in picks
			if group == "58_am_strassenkern"}, {"grenzt_an_kern"})

	def test_reproducible_selection_independent_of_feature_order(self):
		original, _ = sample_groups(self.features)
		reversed_output, _ = sample_groups(list(reversed(self.features)))
		self.assertEqual([(group, feat["properties"]["id"]) for group, feat in original],
			[(group, feat["properties"]["id"]) for group, feat in reversed_output])
		shuffled = list(self.features)
		random.Random(27).shuffle(shuffled)
		other, _ = sample_groups(shuffled)
		self.assertEqual([feat["properties"]["id"] for _, feat in original],
			[feat["properties"]["id"] for _, feat in other])

	def test_select_small_large_mid_and_spread(self):
		items = [feature for feature in self.features
			if feature["properties"]["einbettung"] == "mehrseitig_verschiedene_klassen"
			and feature["properties"]["f_klasse"] == 69]
		picked = choose_diverse(items, 5)
		areas = [item["properties"]["flaeche_m2"] for item in picked]
		self.assertIn(1, areas)
		self.assertIn(9, areas)
		self.assertIn(5, areas)

	def test_end_to_end_files_and_source_metadata(self):
		with tempfile.TemporaryDirectory() as tmp:
			folder = Path(tmp)
			review, source = local_fixture(folder, self.features)
			original_bytes = source.read_bytes()
			result = create_sample(review, source, folder / "out")
			self.assertEqual(result["objekte"], 25)
			self.assertEqual(source.read_bytes(), original_bytes)
			polys = json.loads((folder / "out" / "pruefbeispiele.geojson").read_text(encoding="utf-8"))
			points = json.loads((folder / "out" / "pruefbeispiele_punkte.geojson").read_text(encoding="utf-8"))
			self.assertEqual(len(polys["features"]), 25)
			self.assertEqual(len(points["features"]), 25)
			for poly, point in zip(polys["features"], points["features"]):
				p = poly["properties"]
				self.assertEqual(p["fmzk_id"], p["fid"] + 10000)
				self.assertEqual(p["klasse_sub_text"], "Beispiel")
				self.assertTrue(shape(poly["geometry"]).covers(shape(point["geometry"])))
				self.assertEqual(p["pruefstatus"], "offen")
			with (folder / "out" / "pruefbeispiele.csv").open(encoding="utf-8-sig", newline="") as fp:
				rows = list(csv.DictReader(fp))
			self.assertEqual(len(rows), 25)
			self.assertEqual(rows[0]["pruef_nr"], "1")
			self.assertTrue(all(row["pruefstatus"] == "offen" for row in rows))

	def test_no_accidental_overwrite_of_manual_review(self):
		with tempfile.TemporaryDirectory() as tmp:
			folder = Path(tmp)
			review, source = local_fixture(folder, self.features)
			create_sample(review, source, folder / "out")
			with self.assertRaises(FileExistsError):
				create_sample(review, source, folder / "out")
			csv_file = folder / "out" / "pruefbeispiele.csv"
			text = csv_file.read_text(encoding="utf-8-sig")
			csv_file.write_text(text.replace(",offen,", ",strassenraum,", 1), encoding="utf-8-sig")
			with self.assertRaisesRegex(ValueError, "manuelle Bewertungen"):
				create_sample(review, source, folder / "out", overwrite=True)
			self.assertIn("strassenraum", csv_file.read_text(encoding="utf-8-sig"))

	def test_no_overwrite_of_annotated_geojson(self):
		with tempfile.TemporaryDirectory() as tmp:
			folder = Path(tmp)
			review, source = local_fixture(folder, self.features)
			create_sample(review, source, folder / "out")
			geojson_path = folder / "out" / "pruefbeispiele.geojson"
			data = json.loads(geojson_path.read_text(encoding="utf-8"))
			data["features"][0]["properties"]["pruefnotiz"] = "In QGIS kontrolliert"
			geojson_path.write_text(json.dumps(data), encoding="utf-8")
			with self.assertRaisesRegex(ValueError, "vorhandene GeoJSON"):
				create_sample(review, source, folder / "out", overwrite=True)

	def test_reject_stale_or_mismatched_sources(self):
		with tempfile.TemporaryDirectory() as tmp:
			folder = Path(tmp)
			review, source = local_fixture(folder, self.features)
			picks, _ = sample_groups(self.features)
			fid = picks[0][1]["properties"]["id"]
			with sqlite3.connect(source) as conn:
				conn.execute("UPDATE fmzk SET F_KLASSE=11 WHERE id=?", (fid,))
			with self.assertRaisesRegex(ValueError, "weicht"):
				lookup_original_ids(source, picks)
			stale = [{**f, "properties": dict(f["properties"])} for f in self.features]
			stale[0]["properties"].pop("einbettung")
			review.write_text(json.dumps({"type": "FeatureCollection", "features": stale}))
			with self.assertRaisesRegex(ValueError, "veraltet"):
				read_review(review)

	def test_group_shortage_fails_without_guessing(self):
		smaller = [f for f in self.features if f["properties"]["f_klasse"] != 58]
		with self.assertRaisesRegex(ValueError, "verfügbare Objekte"):
			sample_groups(smaller)


if __name__ == "__main__":
	unittest.main()
