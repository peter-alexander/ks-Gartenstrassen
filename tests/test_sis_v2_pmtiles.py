"""Tests für den eigenständigen SIS-V2-PMTiles-Export."""
import json
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
				"abschnitt_flaeche_m2":150,"boden_pct":10,
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


if __name__ == "__main__":
	unittest.main()
