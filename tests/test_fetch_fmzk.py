import json
import unittest
from urllib.parse import parse_qs, urlparse
from scripts.fetch_fmzk import get_url, parse_bbox, summarize, validate_geojson, validate_shape_zip


class FetchFmzkTest(unittest.TestCase):
	def test_bbox(self):
		self.assertEqual(parse_bbox("16.361012,48.221226,16.366948,48.224902"), (16.361012, 48.221226, 16.366948, 48.224902))
		for wrong in ("16.4,48.2,16.3,48.3", "16.3,48.2,16.8,48.4", "foo"):
			with self.subTest(wrong=wrong), self.assertRaises(ValueError):
				parse_bbox(wrong)

	def test_wfs_10_coordinates_and_layer(self):
		url = get_url("ogdwien:FMZKVERKEHR1OGD", (16.361012, 48.221226, 16.366948, 48.224902), "json", 5000)
		params = parse_qs(urlparse(url).query)
		self.assertEqual(params["version"], ["1.0.0"])
		self.assertEqual(params["bbox"], ["16.361012,48.221226,16.366948,48.224902,EPSG:4326"])
		self.assertEqual(params["typeName"], ["ogdwien:FMZKVERKEHR1OGD"])

	def test_geojson_validation_and_class_summary(self):
		example = {"type": "FeatureCollection", "features": [
			{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[16.3, 48.2], [16.31, 48.2], [16.3, 48.2]]]}, "properties": {"F_KLASSE": 21}},
			{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[16.3, 48.2], [16.31, 48.2], [16.3, 48.2]]]}, "properties": {"F_KLASSE": 23}},
		]}
		data = validate_geojson(json.dumps(example).encode(), max_features=3)
		self.assertEqual(summarize(data)["f_klasse_counts"], {"21": 1, "23": 1})
		with self.assertRaises(ValueError):
			validate_geojson(json.dumps(example).encode(), max_features=2)
		with self.assertRaises(ValueError):
			validate_geojson(json.dumps({**example, "totalFeatures": 3}).encode(), max_features=10)
		with self.assertRaises(ValueError):
			validate_geojson(b"<ServiceException/>", max_features=10)

	def test_invalid_zip(self):
		with self.assertRaises(ValueError):
			validate_shape_zip(b"not a ZIP")


if __name__ == "__main__":
	unittest.main()
