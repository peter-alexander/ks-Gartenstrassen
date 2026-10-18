import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pyproj import Transformer
from shapely.geometry import box

import scripts.analyze_kataster as kat


class KatasterUsageTests(unittest.TestCase):
	def test_wien_edge_tile_without_fmzk_core_skips_bev_and_writes_zero_report(self):
		# 20 gültige FMZK-Polygone ohne Kernklasse 21/23/24/25/33/39.
		# Ein leeres Kataster-Suchergebnis ist nicht gleich einem BEV-Fehler.
		with tempfile.TemporaryDirectory() as tmp:
			fmzk = Path(tmp) / "fmzk.gpkg"
			fmzk.write_bytes(b"synthetic local FMZK source")
			out = Path(tmp) / "kataster"
			features = [(i, 69, "Grünfläche", box(i, 0, i+0.25, 1))
				for i in range(20)]
			manifest = {"feature_count": 20,
				"bbox_lon_lat": [16.3, 48.2, 16.31, 48.21]}
			with patch.object(kat, "load_polygons", return_value=(
				features, manifest, box(0, 0, 25, 25), [])), patch.object(
				kat, "read_tiles", side_effect=AssertionError(
					"Kernfreie Kachel darf keine BEV-Daten abfragen")), patch.object(
				kat, "load_parcel_details", side_effect=AssertionError(
					"Kernfreie Kachel darf keine API-Details abfragen")):
				report = kat.run(fmzk, out, Path(tmp) / "cache")
			self.assertTrue(report["kein_fmzk_kern_im_ausschnitt"])
			self.assertTrue(report["kataster_uebersprungen_ohne_kern"])
			self.assertEqual(report["fmzk_quell_features"], 20)
			self.assertEqual(report["grundstuecke"], 0)
			self.assertEqual(report["tiles_abgerufen"], [])
			self.assertEqual(report["fmzk_kern_klassen"], [21, 23, 24, 25, 33, 39])
			self.assertEqual(report["fmzk_sha256"], kat.checksum(fmzk))
			self.assertEqual(json.loads((out / "kataster_grundstuecke.geojson").read_text())[
				"features"], [])
			self.assertEqual(json.loads((out / "kataster_nfl_ausschnitt.geojson").read_text())[
				"features"], [])
			self.assertTrue((out / "kataster_bericht.json").exists())

	def test_kern_class_25_must_not_take_empty_cadastral_path(self):
		with tempfile.TemporaryDirectory() as tmp:
			fmzk = Path(tmp) / "fmzk.gpkg"
			fmzk.write_bytes(b"synthetic fmzk")
			with patch.object(kat, "load_polygons", return_value=(
				[(1, 25, "Gehweg, Radweg", box(0, 0, 1, 1))],
				{"feature_count": 1,
				 "bbox_lon_lat": [16.3, 48.2, 16.31, 48.21]},
				box(-5, -5, 10, 10), [])), patch.object(kat, "read_tiles",
				side_effect=RuntimeError("BEV-Stufe wurde korrekt betreten")):
				with self.assertRaisesRegex(RuntimeError, "BEV-Stufe"):
					kat.run(fmzk, Path(tmp) / "kataster", Path(tmp) / "cache")

	def test_wien_parcel_guard_checks_1587_before_optional_api_details(self):
		# Der Wien-Gesamtlauf übergibt 2500 als explizites Maximum;
		# der normale Kataster-Standard bleibt 250.
		source = Path("synthetic_wien_fmzk.gpkg")
		core = box(0, 0, 10, 10)
		features = [(1, 25, "Gehweg, Radweg", core)]
		manifest = {"bbox_lon_lat": [16.3, 48.2, 16.31, 48.21],
			"feature_count": 1}
		clip = box(-5, -5, 15, 15)
		shared_parcel = box(0, 0, 1, 1)
		entries = {("01001", str(i)): shared_parcel
			for i in range(1587)}
		with patch.object(kat, "load_polygons",
			return_value=(features, manifest, clip, [])), patch.object(
			kat, "read_tiles", return_value=(entries, [], [])), patch.object(
			kat, "load_parcel_details",
			side_effect=RuntimeError("Limit akzeptiert; Detailsphase erreicht")) as details:
			with self.assertRaisesRegex(RuntimeError, "Detailsphase erreicht"):
				kat.run(source, max_parcels=2500)
			details.assert_called_once()
			details.reset_mock()
			with self.assertRaisesRegex(ValueError,
				"1587 getroffene Grundstücke, maximal 1500"):
				kat.run(source, max_parcels=1500)
			details.assert_not_called()

	def test_wien_parcel_guard_still_rejects_above_2500(self):
		source = Path("synthetic_wien_fmzk.gpkg")
		core = box(0, 0, 10, 10)
		entries = {("01001", str(i)): box(0, 0, 1, 1)
			for i in range(2501)}
		with patch.object(kat, "load_polygons", return_value=(
			[(1,21,"Fahrbahn",core)],
			{"bbox_lon_lat": [16.3,48.2,16.31,48.21],
				"feature_count":1}, box(-5,-5,15,15), [])), patch.object(
			kat, "read_tiles", return_value=(entries,[],[])), patch.object(
			kat, "load_parcel_details",
			side_effect=AssertionError("Darf keine Detailphase aufrufen")) as details:
			with self.assertRaisesRegex(ValueError,
				"2501 getroffene Grundstücke, maximal 2500"):
				kat.run(source, max_parcels=2500)
			details.assert_not_called()

	def test_wien_pipeline_sets_cadastral_guard_explicitly(self):
		script = (Path(__file__).resolve().parents[1] /
			"scripts/run-wien-gartenstrassen.sh").read_text(encoding="utf-8")
		self.assertIn("--max-parcels 2500", script)
		self.assertNotIn("--max-parcels 1500", script)

	def test_cadastral_ids_and_endpoint_match_kartensammlung(self):
		self.assertEqual(kat.cadastral_key({"kgez": "01004", "gnr": "123/4"}), ("01004", "123/4"))
		self.assertEqual(kat.cadastral_key({"kg": 1004, "gnr": ".17"}), ("01004", ".17"))
		self.assertIsNone(kat.cadastral_key({"gnr": "17"}))
		self.assertEqual(kat.detail_url("01004", "123/4"),
			"https://kataster.bev.gv.at/api/gst/01004/123/4/")

	def test_parse_whole_parcel_with_known_names_and_codes(self):
		detail = {"type": "Feature", "properties": {
			"rstatus": "G",
			"nutzungen": {
				"foo": {"nutzung": "Straßenverkehrsanlagen", "fl": 220},
				"bar": {"nutzung": "Verkehrsrandflächen", "fl": 30},
			},
		}}
		usage, unknown, props = kat.parse_whole_parcel(detail)
		self.assertEqual(usage, {65: 30, 95: 220})
		self.assertFalse(unknown)
		self.assertEqual(props["rstatus"], "G")
		self.assertEqual(kat.classify_usages(usage, unknown)[0], "A")

	def test_mixed_nutzung_includes_areas_outside_test_bbox(self):
		detail = {"properties": {
			"nutzungen": [
				{"nutzung": "Straßenverkehrsanlagen", "fl": 35},
				{"nutzung": "Gärten", "fl": 320},
				{"nutzung": "Gebäude", "fl": 200},
			]
		}}
		usages, unknown, _ = kat.parse_whole_parcel(detail)
		self.assertEqual(usages[95], 35)
		self.assertEqual(kat.classify_usages(usages, unknown)[0], "B")

	def test_no_street_use_and_only_parking_not_high_confidence(self):
		self.assertEqual(kat.classify_usages({41: 120, 52: 50}, [])[0], "C")
		self.assertEqual(kat.classify_usages({42: 125}, [])[0], "C")
		self.assertEqual(kat.classify_usages({65: 10}, [])[0], "A")

	def test_unknown_and_partial_usage_never_produces_a(self):
		usage, unknown, _ = kat.parse_whole_parcel({
			"properties": {"nutzungen": {
				"one": {"nutzung": "Straßenverkehrsanlagen", "fl": 100},
				"two": {"nutzung": "Unbekannte Nutzung", "fl": 2},
			}}
		})
		self.assertEqual(usage, {95: 100})
		self.assertEqual(len(unknown), 1)
		self.assertEqual(kat.classify_usages(usage, unknown)[0], "D")
		self.assertEqual(kat.classify_usages({}, [])[0], "D")
		with self.assertRaisesRegex(ValueError, "Nutzungsbilanz fehlt"):
			kat.parse_whole_parcel({"properties": {"nutzungen": {}}})

	def test_read_tile_with_correct_webmercator_y_axis(self):
		# Kachel-Geometrie ist im lokalen Extent-Koordinatensystem,
		# Y wächst im PBF nach unten.
		z, x, y = 16, 35740, 22722
		data = {
			"gst": {"extent": 4096, "features": [
				{"geometry": {
					"type": "Polygon", "coordinates": [[
						[0, 0], [200, 0], [200, 200], [0, 200], [0, 0]
					]],
				}, "properties": {"kgez": "01004", "gnr": "1"}},
			]},
			"nfl": {"extent": 4096, "features": [
				{"geometry": {
					"type": "Polygon", "coordinates": [[
						[0, 0], [200, 0], [200, 200], [0, 200], [0, 0]
					]],
				}, "properties": {"ns": 95}},
			]},
		}
		with patch.object(kat.mapbox_vector_tile, "decode", return_value=data) as decoder:
			got = kat.decode_tile(b"some pbf", z, x, y)
			decoder.assert_called_once_with(b"some pbf",
				default_options={"y_coord_down": True})
		self.assertEqual(len(got["gst"]), 1)
		self.assertEqual(got["nfl"][0][0]["ns"], 95)
		minx, miny, maxx, maxy = got["gst"][0][1].bounds
		self.assertGreater(maxx, minx)
		self.assertGreater(maxy, miny)
		radius = kat.WEBMERCATOR_RADIUS
		width = 2 * radius / 2**z
		reprojection = Transformer.from_crs("EPSG:3857", "EPSG:31256", always_xy=True)
		origin = reprojection.transform(-radius + x * width, radius - y * width)
		self.assertAlmostEqual(got["gst"][0][1].exterior.coords[0][0], origin[0], delta=0.5)
		self.assertAlmostEqual(got["gst"][0][1].exterior.coords[0][1], origin[1], delta=0.5)

	def test_core_selection_uses_polygon_intersection_not_point_contact(self):
		core = box(0, 0, 10, 10)
		clip = box(-5, -5, 20, 20)
		parcels = {
			("01004", "1"): box(-5, -5, 5, 15),
			("01004", "2"): box(5, -5, 15, 15),
			("01004", "3"): box(10, 10, 15, 15),
		}
		nfl = [({"ns": 95}, box(-5, -5, 5, 15)),
			({"ns": 52}, box(5, -5, 15, 15))]
		details = {
			("01004", "1"): {"properties": {"nutzungen": [{"nutzung": "Straßenverkehrsanlagen", "fl": 500}]}},
			("01004", "2"): {"properties": {"nutzungen": [
				{"nutzung": "Straßenverkehrsanlagen", "fl": 100},
				{"nutzung": "Gärten", "fl": 600},
			]}},
		}
		rows, polys, usages = kat.build_results(core, parcels, nfl, clip, details)
		self.assertEqual([(row["table"]["gnr"], row["table"]["klasse"]) for row in rows],
			[("1", "A"), ("2", "B")])
		self.assertEqual(len(polys), 2)
		self.assertTrue(all(not feature["properties"]["vollstaendig"] for feature in usages))
		self.assertEqual(rows[1]["table"]["strassen_nutzung_m2"], 100)
		self.assertEqual(rows[1]["table"]["sonstige_nutzung_m2"], 600)

	def test_missing_detail_is_d_not_fake_a(self):
		core = box(0, 0, 10, 10)
		rows, _, _ = kat.build_results(core, {("01004", "1"): core},
			[({"ns": 95}, core)], core, {("01004", "1"): {"error": "503"}})
		self.assertEqual(rows[0]["table"]["klasse"], "D")

	def test_cache_offline_and_atomic_update(self):
		with tempfile.TemporaryDirectory() as tmp:
			path = Path(tmp) / "nested" / "tile.pbf"
			with patch.object(kat, "fetch_bytes", return_value=b"tile") as fetch:
				self.assertEqual(kat.cached_request("https://x.test", path), b"tile")
				self.assertEqual(kat.cached_request("https://x.test", path, offline=True), b"tile")
				fetch.assert_called_once()
				self.assertEqual(kat.cached_request("https://x.test", path, refresh=True), b"tile")
				self.assertEqual(fetch.call_count, 2)
			with self.assertRaises(FileNotFoundError):
				kat.cached_request("https://x.test", path.parent / "missing", offline=True)

	def test_default_uses_cache_only_without_network_calls(self):
		with tempfile.TemporaryDirectory() as tmp:
			cache = Path(tmp)
			key1 = ("01004", "23")
			key2 = ("01004", "24")
			saved = cache / "details" / key1[0] / "23.json"
			saved.parent.mkdir(parents=True)
			saved.write_text(json.dumps({"properties": {
				"nutzungen": [{"nutzung": "Straßenverkehrsanlagen", "fl": 11}]
			}}), encoding="utf-8")
			with patch.object(kat, "cached_request", side_effect=AssertionError("Unerlaubter Netzabruf")):
				details, failures, reason = kat.load_parcel_details([key1, key2], cache)
			self.assertFalse(failures)
			self.assertEqual(reason, "")
			self.assertEqual(kat.classify_usages(*kat.parse_whole_parcel(details[key1])[:2])[0], "A")
			self.assertEqual(details[key2]["error"], "keine API-Daten im Cache")

	def test_api_failure_trips_circuit_breaker_after_first_request(self):
		from urllib.error import HTTPError
		with tempfile.TemporaryDirectory() as tmp:
			cache = Path(tmp)
			keys = [("01004", str(number)) for number in range(1, 6)]
			with patch.object(kat, "cached_request",
				side_effect=HTTPError("https://kataster.bev.gv.at/api", 503,
					"Service Unavailable", {}, None)) as request:
				details, failures, reason = kat.load_parcel_details(keys, cache, online=True,
					pause=0)
			self.assertEqual(request.call_count, 1)
			self.assertEqual(len(failures), 1)
			self.assertIn("503", reason)
			self.assertTrue(all("error" in details[key] for key in keys))

	def test_missing_api_does_not_promote_tile_only_95_to_a(self):
		core = box(0, 0, 10, 10)
		parcel = {("01004", "7"): core}
		results, _, _ = kat.build_results(core, parcel, [({"ns": 95}, core)],
			core, {("01004", "7"): {"error": "keine API-Daten im Cache"}})
		row = results[0]["table"]
		self.assertEqual(row["klasse"], "D")
		self.assertEqual(row["tile_nutzungshinweis"], "nur_95_65_im_ausschnitt")
		with tempfile.TemporaryDirectory() as tmp:
			report = kat.write_results(Path(tmp), results, [], [], [],
				[16, 48, 17, 49], [])
			self.assertFalse(report["vollstaendige_nutzungsbilanz_aus_api"])
			self.assertEqual(report["grundstuecke_mit_api_nutzungsbilanz"], 0)

	def test_report_contains_completeness_and_three_classes(self):
		core = box(0, 0, 10, 10)
		clip = box(-5, -5, 30, 30)
		parcels = {
			("01004", "1"): box(-5, -5, 4, 15),
			("01004", "2"): box(4, -5, 7, 15),
			("01004", "3"): box(7, -5, 12, 15),
			("01004", "4"): box(9, -5, 12, 15),
		}
		nfl = [({"ns": 95}, core)]
		details = {
			("01004", "1"): {"properties": {"nutzungen": {"1": {"nutzung": "Straßenverkehrsanlagen", "fl": 100}}}},
			("01004", "2"): {"properties": {"nutzungen": {
				"1": {"nutzung": "Verkehrsrandflächen", "fl": 5},
				"2": {"nutzung": "Gärten", "fl": 300},
			}}},
			("01004", "3"): {"properties": {"nutzungen": {"1": {"nutzung": "Gebäude", "fl": 50}}}},
		}
		rows, polygons, uses = kat.build_results(core, parcels, nfl, clip, details)
		with tempfile.TemporaryDirectory() as tmp:
			report = kat.write_results(Path(tmp), rows, polygons, uses,
				[(16, 35740, 22722)], [16.36, 48.22, 16.37, 48.23], [])
			self.assertEqual(report["klassen"], {"A": 1, "B": 1, "C": 1, "D": 1})
			self.assertTrue(report["nfl_geojson_nur_testausschnitt"])
			self.assertFalse(report["vollstaendige_nutzungsbilanz_aus_api"])
			self.assertEqual(report["grundstuecke_mit_api_nutzungsbilanz"], 3)
			self.assertEqual(len(json.loads((Path(tmp) / "kataster_grundstuecke.geojson").read_text())["features"]), 4)


if __name__ == "__main__":
	unittest.main()
