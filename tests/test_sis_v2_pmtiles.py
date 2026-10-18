"""Tests für den eigenständigen SIS-V2-PMTiles-Export."""
import json
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.sis_v2_pmtiles import run


class SISV2PMTilesTests(unittest.TestCase):
	def setUp(self):
		self.temp = tempfile.TemporaryDirectory()
		self.addCleanup(self.temp.cleanup)
		self.root = Path(self.temp.name)
		self.source = self.root/"source.geojson"
		self.output = self.root/"output.pmtiles"

	def _write(self, identifier="10023434", property_identifier="10023434"):
		self.source.write_text(json.dumps({"type":"FeatureCollection","features":[{
			"type":"Feature", "id":identifier,
			"properties":{"gip_id":property_identifier,
				"fow":3,"abschnitt_flaeche_m2":150,"boden_pct":10,
				"nicht_begruent_pct":90},
			"geometry":{"type":"Polygon","coordinates":[[
				[16,48],[16.001,48],[16.001,48.001],[16,48.001],[16,48]]]}
		}]}), encoding="utf-8")

	def test_numeric_string_id_is_passed_to_tippecanoe_as_integer(self):
		self._write()
		captured = {}
		def fake_run(command, check):
			self.assertTrue(check)
			captured.update(json.loads(Path(command[-1]).read_text(encoding="utf-8")))
			Path(command[command.index("-o")+1]).write_bytes(b"pmtiles")
		with patch("scripts.sis_v2_pmtiles.shutil.which", return_value="tippecanoe"), \
				patch("scripts.sis_v2_pmtiles.subprocess.run", side_effect=fake_run):
			report = run(self.source, self.output)
		self.assertEqual(captured["features"][0]["id"], 10023434)
		self.assertEqual(captured["features"][0]["properties"]["gip_id"], "10023434")
		self.assertEqual(report["gip_ids"], 1)

	def test_inconsistent_id_is_rejected_before_export(self):
		self._write(identifier="12", property_identifier="13")
		with patch("scripts.sis_v2_pmtiles.shutil.which", return_value="tippecanoe"):
			with self.assertRaisesRegex(ValueError, "widersprechen"):
				run(self.source, self.output)


	def test_only_street_fow_enters_archive_and_exclusions_reported(self):
		self._write()
		doc = json.loads(self.source.read_text(encoding="utf-8"))
		features = doc["features"]
		for code in (2, 14, 15, 20, 8, 13, 18, 19, 24, 101, 102, 103,
				401, 405, 505, 506, 514, 523, 601, -1):
			feature = json.loads(json.dumps(features[0]))
			feature["id"] = str(code + 10000000)
			feature["properties"]["gip_id"] = feature["id"]
			feature["properties"]["fow"] = code
			features.append(feature)
		self.source.write_text(json.dumps(doc), encoding="utf-8")
		captured = {}
		def fake_run(command, check):
			captured.update(json.loads(Path(command[-1]).read_text(encoding="utf-8")))
			Path(command[command.index("-o")+1]).write_bytes(b"pmtiles")
		with patch("scripts.sis_v2_pmtiles.shutil.which", return_value="tippecanoe"), \
				patch("scripts.sis_v2_pmtiles.subprocess.run", side_effect=fake_run):
			report = run(self.source, self.output)
		self.assertEqual({x["properties"]["fow"] for x in captured["features"]}, {2, 3, 14})
		self.assertEqual(report["gip_ids"], 3)
		self.assertEqual(report["omitted_fow"], len(features)-3)
		self.assertEqual(report["omitted_min_area"], 0)
		self.assertEqual(report["allowed_fow"], [2, 3, 14])
		self.assertIn("505", report["omitted_fow_by_code"])

	def test_missing_fow_is_not_published(self):
		self._write()
		doc = json.loads(self.source.read_text(encoding="utf-8"))
		del doc["features"][0]["properties"]["fow"]
		self.source.write_text(json.dumps(doc), encoding="utf-8")
		with patch("scripts.sis_v2_pmtiles.shutil.which", return_value="tippecanoe"):
			with self.assertRaisesRegex(ValueError, "Keine Features"):
				run(self.source, self.output)
		self.assertFalse(self.output.exists())


	def test_replace_is_atomic_and_failure_keeps_old_archive(self):
		self._write()
		self.output.write_bytes(b"old archive")
		captured = []
		def fake_run(command, check):
			captured.append(command)
			Path(command[command.index("-o")+1]).write_bytes(b"new archive")
		with patch("scripts.sis_v2_pmtiles.shutil.which", return_value="tippecanoe"), \
				patch("scripts.sis_v2_pmtiles.subprocess.run", side_effect=fake_run):
			report = run(self.source, self.output, replace=True)
		self.assertEqual(self.output.read_bytes(), b"new archive")
		self.assertTrue(report["existing_replaced"])
		self.assertEqual(len(captured), 1)
		self.assertFalse(self.output.with_suffix(".filtered.geojson.tmp").exists())
		self.assertFalse(self.output.with_suffix(".tmp.pmtiles").exists())

		self.output.write_bytes(b"previous successful archive")
		def failing_run(command, check):
			Path(command[command.index("-o")+1]).write_bytes(b"partial")
			raise subprocess.CalledProcessError(1, command)
		with patch("scripts.sis_v2_pmtiles.shutil.which", return_value="tippecanoe"), \
				patch("scripts.sis_v2_pmtiles.subprocess.run", side_effect=failing_run):
			with self.assertRaises(subprocess.CalledProcessError):
				run(self.source, self.output, replace=True)
		self.assertEqual(self.output.read_bytes(), b"previous successful archive")
		self.assertFalse(self.output.with_suffix(".filtered.geojson.tmp").exists())
		self.assertFalse(self.output.with_suffix(".tmp.pmtiles").exists())


if __name__ == "__main__":
	unittest.main()
