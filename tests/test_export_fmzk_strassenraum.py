import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from pyproj import Transformer
from shapely.geometry import box, mapping
from shapely.ops import transform

from scripts.export_fmzk_strassenraum import (
	classify_fmzk, read_kataster_masks, write_two_geojson,
)


class FmzkStreetExportTest(unittest.TestCase):
	def test_core_and_cadastral_mask_classify_every_fmzk_polygon_once(self):
		street = box(0, 0, 10, 10)
		other = box(10, 0, 20, 10)
		features = [
			(1, 21, "Fahrbahn", box(11, 0, 13, 2)),
			(2, 69, "Sonstige Grünfläche", box(1, 1, 2, 2)),
			(3, 58, "Grünfläche", box(9, 1, 11, 3)),
			(4, 59, "Befestigte Fläche", box(11, 1, 12, 2)),
			(5, 69, "Baumscheibe ohne nfl", box(25, 1, 26, 2)),
		]
		output = classify_fmzk(features, street, other)
		self.assertEqual(len(output), len(features))
		self.assertEqual([target for target, _, _ in output],
			["strassenraum", "strassenraum", "uebrige", "uebrige", "uebrige"])
		self.assertEqual([properties["fid"] for _, properties, _ in output],
			[feature[0] for feature in features])
		self.assertEqual(output[0][1]["pruefhinweis"], "kern_abweichung_zum_kataster")
		self.assertEqual(output[2][1]["grund"], "teilweise_strassenlage_pruefen")
		self.assertEqual(output[4][1]["grund"], "kataster_teilweise_ohne_nutzung")
		for feature, (_, _, geom) in zip(features, output):
			self.assertEqual(feature[3], geom)

	def test_class_25_is_paved_street_even_without_cadastral_street_mask(self):
		street = box(0, 0, 2, 2)
		other = box(10, 0, 20, 10)
		output = classify_fmzk([
			(1, 25, "Gehweg, Radweg", box(12, 2, 18, 5)),
			(2, 26, "Private Verkehrsfläche", box(12, 5, 18, 8)),
			(3, 69, "Grünfläche", box(12, 8, 18, 9)),
		], street, other)
		self.assertEqual([part[0] for part in output],
			["strassenraum", "uebrige", "uebrige"])
		self.assertEqual(output[0][1]["grund"], "fmzk_kern")
		self.assertEqual(output[0][1]["pruefhinweis"], "kern_abweichung_zum_kataster")

	def test_conflicting_kataster_codes_not_assumed_road(self):
		# Konflikte zwischen 95 und anderen Nutzungen sind keine
		# zuverlässige Grundlage für eine positive Zuordnung.
		feature = (9, 69, "Grün", box(0, 0, 10, 10))
		output = classify_fmzk([feature], box(0, 0, 10, 10), box(0, 0, 6, 10))
		self.assertEqual(output[0][0], "uebrige")
		with self.assertRaisesRegex(ValueError, "--min-strassenanteil"):
			classify_fmzk([feature], box(0, 0, 10, 10), box(20, 0, 30, 10), minimum_share=0.1)

	def test_tile_frags_union_repairs_and_check_bbox(self):
		with tempfile.TemporaryDirectory() as tmp:
			folder = Path(tmp)
			source_crs = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform
			to_geojson = lambda geom: mapping(transform(source_crs, geom))
			manifest = {"bbox_lon_lat": [16.36, 48.22, 16.37, 48.23]}
			west, south, east, north = manifest["bbox_lon_lat"]
			clip = transform(Transformer.from_crs("EPSG:4326", "EPSG:31256", always_xy=True).transform,
				box(west, south, east, north))
			cx, cy = Transformer.from_crs("EPSG:4326", "EPSG:31256", always_xy=True).transform(16.365, 48.225)
			first = box(cx - 15, cy - 5, cx - 5, cy + 5)
			second = box(cx - 5, cy - 5, cx + 5, cy + 5)
			parcel = {"type": "Feature", "properties": {"kgez": "01002", "gnr": "100"},
				"geometry": to_geojson(box(cx - 15, cy - 5, cx + 5, cy + 5))}
			def usage(code, geometry):
				return {"type": "Feature", "properties": {
					"kgez": "01002", "gnr": "100", "ns": code, "vollstaendig": False},
					"geometry": to_geojson(geometry)}
			(folder / "kataster_bericht.json").write_text(json.dumps({
				"zoom": 16, "fmzk_kern_klassen": [21,23,24,25,33,39],
				"bbox_lon_lat": manifest["bbox_lon_lat"], "grundstuecke": 1}))
			(folder / "kataster_grundstuecke.geojson").write_text(json.dumps({
				"type": "FeatureCollection", "features": [parcel]}))
			(folder / "kataster_nfl_ausschnitt.geojson").write_text(json.dumps({
				"type": "FeatureCollection", "features": [usage(95, first), usage(95, first), usage(52, second)]}))
			street, other, stats = read_kataster_masks(folder, clip, manifest)
			self.assertAlmostEqual(street.area, first.area, delta=0.2)
			self.assertAlmostEqual(other.area, second.area, delta=0.2)
			self.assertEqual(stats["nfl_fragmente"], 3)
			bad = {"bbox_lon_lat": [16.35, 48.22, 16.37, 48.23]}
			with self.assertRaisesRegex(ValueError, "verschiedenen Testausschnitten"):
				read_kataster_masks(folder, clip, bad)

	def test_writes_two_separate_geojson_with_original_attributes(self):
		with tempfile.TemporaryDirectory() as tmp:
			folder = Path(tmp)
			db = folder / "fmzk_test.gpkg"
			with sqlite3.connect(db) as conn:
				conn.execute('CREATE TABLE fmzk (id INTEGER PRIMARY KEY, FMZK_ID INTEGER, KLASSE_SUB_TEXT TEXT)')
				conn.execute('INSERT INTO fmzk VALUES (1, 9982, "Grün")')
				conn.execute('INSERT INTO fmzk VALUES (2, 9983, "Weg")')
				conn.execute('INSERT INTO fmzk VALUES (3, 9984, "Innenhof")')
			classified = classify_fmzk([
				(1, 69, "Grün", box(100, 200, 102, 202)),
				(2, 21, "Fahrbahn", box(110, 200, 112, 202)),
				(3, 51, "Innenhof", box(110, 210, 112, 212)),
			], box(100, 200, 103, 203), box(105, 200, 113, 203))
			report = write_two_geojson(classified, db, folder / "out",
				mask_stats={}, minimum_share=0.95)
			self.assertEqual(report["fmzk_features_gesamt"], 3)
			self.assertEqual(report["features"], {"strassenraum": 2, "uebrige": 1})
			street = json.loads((folder / "out" / "fmzk_strassenraum.geojson").read_text())
			other = json.loads((folder / "out" / "fmzk_uebrige_flaechen.geojson").read_text())
			self.assertEqual(len(street["features"]), 2)
			self.assertEqual(len(other["features"]), 1)
			self.assertEqual({f["properties"]["fid"] for f in street["features"]}
				| {f["properties"]["fid"] for f in other["features"]}, {1, 2, 3})
			self.assertEqual(street["features"][0]["properties"]["fmzk_id"], 9982)
			self.assertEqual(street["features"][0]["properties"]["klasse_sub_text"], "Grün")
			self.assertEqual(street["features"][1]["properties"]["grund"], "fmzk_kern")


if __name__ == "__main__":
	unittest.main()
