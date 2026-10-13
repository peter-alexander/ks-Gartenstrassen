import json
from pathlib import Path
import tempfile
import unittest

from shapely.geometry import box, mapping

from scripts.analyze_fmzk import analyze, parse_class


class AnalyzeFmzkTest(unittest.TestCase):
	def make_input(self, root, features1, features2):
		folder = root / "raw"
		folder.mkdir()
		layers = {"verkehr1": features1, "verkehr2": features2}
		manifest = {"crs": "EPSG:4326", "bbox_lon_lat": [16.35, 48.19, 16.36, 48.20],
			"layers": {key: {"feature_count": len(features)} for key, features in layers.items()}}
		(folder / "manifest.json").write_text(json.dumps(manifest))
		for name, feats in layers.items():
			(folder / f"fmzk_{name}.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
		return folder

	@staticmethod
	def feature(code, polygon, id):
		return {"type": "Feature", "id": id, "geometry": mapping(polygon), "properties": {"F_KLASSE": code}}

	def test_area_is_clipped_and_overlaps_are_measured(self):
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			raw = self.make_input(root,
				[self.feature(21, box(16.345, 48.19, 16.355, 48.20), "A"),
				self.feature(21, box(16.35, 48.19, 16.355, 48.20), "B")],
				[self.feature(51, box(16.352, 48.192, 16.354, 48.198), "C")])
			report = analyze(raw, root / "processed")
			self.assertEqual(len(report["categories"]), 2)
			area = report["bbox_area_m2"]
			self.assertAlmostEqual(report["categories"][0]["fläche_m2"] / area, 0.5, delta=0.004)
			self.assertGreater(report["overlap_across_classes_m2"], 0)
			result = json.loads((root / "processed" / "fmzk_ausschnitt.geojson").read_text())
			self.assertEqual(len(result["features"]), 3)
			self.assertEqual(result["features"][0]["properties"]["QUELLE"], "verkehr1")
			self.assertLessEqual(max(p[0] for p in result["features"][0]["geometry"]["coordinates"][0]), 16.36)

	def test_manifest_count_mismatch_is_rejected(self):
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			raw = self.make_input(root, [], [])
			manifest_path = raw / "manifest.json"
			manifest = json.loads(manifest_path.read_text())
			manifest["layers"]["verkehr1"]["feature_count"] = 1
			manifest_path.write_text(json.dumps(manifest))
			with self.assertRaisesRegex(ValueError, "Manifest"):
				analyze(raw, root / "processed")

	def test_unknown_class_rejected(self):
		with self.assertRaisesRegex(ValueError, "unbekannter"):
			parse_class(12345, "verkehr1", "id1")
		with self.assertRaisesRegex(ValueError, "nichtganzzahlig"):
			parse_class(21.5, "verkehr1", "id1")

	def test_invalid_geometry_is_repaired_and_reported(self):
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			bad = {"type": "Polygon", "coordinates": [[[16.35, 48.19], [16.36, 48.20], [16.35, 48.20], [16.36, 48.19], [16.35, 48.19]]]}
			raw = self.make_input(root, [{"type": "Feature", "id": "bad", "geometry": bad, "properties": {"F_KLASSE": 21}}], [])
			report = analyze(raw, root / "processed")
			self.assertEqual(len(report["geometry_repairs"]), 1)
			self.assertEqual(report["geometry_repairs"][0]["feature_id"], "bad")
			self.assertGreater(report["categories"][0]["fläche_m2"], 0)
			data = json.loads((root / "processed" / "fmzk_ausschnitt.geojson").read_text())
			self.assertTrue(data["features"][0]["properties"]["GEOM_FIX"])

	def test_invalid_line_like_geometry_cannot_be_counted_as_area(self):
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			bad = {"type": "Polygon", "coordinates": [[[16.35, 48.19], [16.355, 48.195], [16.36, 48.20], [16.35, 48.19]]]}
			raw = self.make_input(root, [{"type": "Feature", "id": "noarea", "geometry": bad, "properties": {"F_KLASSE": 21}}], [])
			with self.assertRaisesRegex(ValueError, "nicht in gültige Polygonfläche repariert"):
				analyze(raw, root / "processed")


if __name__ == "__main__":
	unittest.main()
