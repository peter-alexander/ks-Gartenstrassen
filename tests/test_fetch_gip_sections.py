import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from pyproj import Transformer
from shapely.geometry import box

from scripts.fetch_gip_sections import (
	LAYERS, MAX_RESPONSE_BYTES, VIEW_NAMES, RAW_NAMES,
	build_wfs_url, request_bbox, run, validate_layer,
)


TO_METRIC = Transformer.from_crs(
	"EPSG:4326", "EPSG:31256", always_xy=True).transform
TEST_X, TEST_Y = 16.363, 48.223


def area():
	x, y = TO_METRIC(TEST_X, TEST_Y)
	return box(x - 70, y - 60, x + 70, y + 60)


def feature(kind, gid, *, fid=None, coords=None, name="Pramergasse"):
	if coords is None:
		coords = (
			[[16.3628, 48.223], [16.3632, 48.223]]
			if kind == "achsen" else [16.363, 48.223]
		)
	return {
		"type": "Feature",
		"id": fid if fid is not None else f"{kind}.{gid}",
		"geometry": {
			"type": "LineString" if kind == "achsen" else "Point",
			"coordinates": coords,
		},
		"properties": {
			"GIP_OBJECTID": gid,
			"FEATURENAME": name,
			"NODEFROM_OBJECTID": 101 if kind == "achsen" else None,
			"NODETO_OBJECTID": 102 if kind == "achsen" else None,
		},
	}


def payload(kind, *, items=None, **kwargs):
	if items is None:
		items = [feature(kind, 123)]
	return json.dumps({
		"type": "FeatureCollection",
		"crs": {"type": "name", "properties": {
			"name": "urn:ogc:def:crs:EPSG::4326",
		}},
		"features": items,
		**kwargs,
	}).encode("utf-8")


class GIPSectionsTests(unittest.TestCase):
	def setUp(self):
		self.clip = area()
		self.bbox = request_bbox(self.clip, padding_m=75)

	def test_request_is_bounded_and_uses_explicit_wfs_crs(self):
		for layer in LAYERS.values():
			url = build_wfs_url(layer, self.bbox, max_features=600)
			values = parse_qs(urlparse(url).query)
			self.assertEqual(values["typeName"], [layer])
			self.assertEqual(values["version"], ["1.1.0"])
			self.assertEqual(values["outputFormat"], ["json"])
			self.assertEqual(values["srsName"], ["EPSG:4326"])
			self.assertTrue(values["bbox"][0].endswith(",EPSG:3857"))
			self.assertEqual(values["maxFeatures"], ["600"])
		for kind in ("bogus", "ogdwien:ALL"):
			with self.assertRaisesRegex(ValueError, "Unbekannter"):
				build_wfs_url(kind, self.bbox)
		with self.assertRaisesRegex(ValueError, "zu groß"):
			build_wfs_url(LAYERS["achsen"], (0, 0, 6000, 300))
		with self.assertRaisesRegex(ValueError, "Randbereich"):
			request_bbox(self.clip, padding_m=1000)

	def test_validates_geometry_and_preserves_unmerged_duplicate_ids(self):
		raw = payload("achsen", items=[
			feature("achsen", 123, fid="edge.1"),
			feature("achsen", 123, fid="edge.2",
				coords=[[16.363, 48.223], [16.3632, 48.2231]]),
		])
		_, view, summary = validate_layer(raw, "achsen", self.bbox)
		self.assertEqual(summary["anzahl"], 2)
		self.assertEqual(summary["doppelte_gip_ids"], {"123": 2})
		self.assertEqual(len(view["features"]), 2)
		self.assertEqual([x["id"] for x in view["features"]],
			["edge.1", "edge.2"])
		self.assertTrue(all(f["properties"]["gip_objectid"] == "123"
			for f in view["features"]))
		self.assertEqual(view["features"][0]["properties"]["name"], "Pramergasse")
		self.assertEqual(view["features"][0]["properties"]["node_from"], 101)

	def test_rejects_incomplete_and_malformed_wfs_answers(self):
		with self.assertRaisesRegex(ValueError, "keine GeoJSON"):
			validate_layer(b"<ServiceException/>", "achsen", self.bbox)
		with self.assertRaisesRegex(ValueError, "Limit"):
			validate_layer(payload("knoten"), "knoten", self.bbox,
				max_features=1)
		with self.assertRaisesRegex(ValueError, "unvollständig"):
			validate_layer(payload("knoten", totalFeatures=3),
				"knoten", self.bbox)
		with self.assertRaisesRegex(ValueError, "ungültiges.*numberMatched"):
			validate_layer(payload("knoten", numberMatched="invalid"),
				"knoten", self.bbox)
		with self.assertRaisesRegex(ValueError, "keine GIP-Features"):
			validate_layer(payload("knoten", items=[]),
				"knoten", self.bbox)
		with self.assertRaisesRegex(ValueError, "überschreitet"):
			validate_layer(b"x" * (MAX_RESPONSE_BYTES + 1),
				"knoten", self.bbox)

	def test_invalid_coords_crs_attributes_and_geometries_fail_closed(self):
		samples = [
			(payload("achsen", items=[
				feature("achsen", 1,
					coords=[[48.223, 16.363], [48.224, 16.364]]),
			]), "nicht plausibel"),
			(payload("knoten", items=[
				feature("knoten", 1, coords=[16.4, 48.3]),
			]), "außerhalb der WFS-BBOX"),
			(payload("achsen", items=[
				{**feature("achsen", 1),
					"properties": {"FEATURENAME": "Ohne ID"}},
			]), "GIP_OBJECTID"),
			(payload("achsen", items=[
				{**feature("achsen", 1), "geometry": {
					"type": "Point", "coordinates": [16.363, 48.223]}},
			]), "statt"),
		]
		for raw, pattern in samples:
			with self.subTest(pattern=pattern):
				with self.assertRaisesRegex(ValueError, pattern):
					validate_layer(raw,
						"knoten" if pattern == "außerhalb der WFS-BBOX"
						else "achsen", self.bbox)
		d = json.loads(payload("achsen"))
		d["crs"]["properties"]["name"] = "EPSG:3857"
		with self.assertRaisesRegex(ValueError, "CRS"):
			validate_layer(json.dumps(d).encode(), "achsen", self.bbox)

	def test_network_failure_does_not_leave_partial_files(self):
		with tempfile.TemporaryDirectory() as temp:
			output = Path(temp) / "gip"
			def fetch(url):
				if "STRASSENKNOTENOGD" in url:
					raise OSError("Netzfehler Knoten")
				return payload("achsen")
			with patch("scripts.fetch_gip_sections.load_polygons",
				return_value=([], {"bbox_lon_lat": [
					16.361012, 48.221226, 16.366948, 48.224902
				]}, self.clip, [])):
				with self.assertRaisesRegex(OSError, "Netzfehler"):
					run(output=output, downloader=fetch)
			self.assertFalse(output.exists())

	def test_end_to_end_cache_and_refresh_controls(self):
		with tempfile.TemporaryDirectory() as temp:
			output = Path(temp) / "gip"
			def fetch(url):
				return payload("knoten") if "STRASSENKNOTENOGD" in url else payload("achsen")
			with patch("scripts.fetch_gip_sections.load_polygons",
				return_value=([], {"bbox_lon_lat": [
					16.361012, 48.221226, 16.366948, 48.224902
				]}, self.clip, [])):
				report = run(output=output, downloader=fetch)
				self.assertEqual(set(report["datensaetze"]), {"achsen", "knoten"})
				self.assertEqual(report["status"],
					"GIP-QUELLPROBE – KEINE STRASSENABSCHNITTS-FLAECHEN")
				self.assertEqual(report["datensaetze"]["achsen"]["anzahl"], 1)
				self.assertEqual(report["datensaetze"]["knoten"]["anzahl"], 1)
				for name in [*RAW_NAMES.values(), *VIEW_NAMES.values()]:
					self.assertTrue((output / name).is_file())
				original = (output / RAW_NAMES["achsen"]).read_bytes()
				view = json.loads((output / VIEW_NAMES["knoten"]).read_text())
				self.assertEqual(view["features"][0]["geometry"]["type"], "Point")
				cached = run(output=output, offline=True)
				self.assertEqual(cached["created_utc"], report["created_utc"])
				self.assertEqual((output / RAW_NAMES["achsen"]).read_bytes(),
					original)
				with self.assertRaisesRegex(ValueError, "anderen"):
					run(output=output, padding_m=76, offline=True)
				# Manipulierte lokale Rohdaten nie ohne Prüfung übernehmen.
				(output / RAW_NAMES["achsen"]).write_bytes(payload("achsen",
					items=[feature("achsen", 987)]))
				with self.assertRaisesRegex(ValueError, "SHA-256"):
					run(output=output, offline=True)
				refreshed = run(output=output, refresh=True, downloader=fetch)
				self.assertEqual((output / RAW_NAMES["achsen"]).read_bytes(),
					original)
				self.assertEqual(refreshed["datensaetze"]["achsen"]["anzahl"], 1)
				with self.assertRaisesRegex(ValueError, "schließen"):
					run(output=output, offline=True, refresh=True)


if __name__ == "__main__":
	unittest.main()
