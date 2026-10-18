"""Umzug des Wiener SIS-Arbeitsverzeichnisses ohne Änderung der Provenienz."""
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from pyproj import Transformer
from shapely.geometry import box, mapping
from shapely.ops import transform

from scripts.wienwide_grid import build_manifest, checksum, read_manifest, write_manifest


class SISWienRelocationTests(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.addCleanup(self.tmp.cleanup)
		self.root = Path(self.tmp.name)
		self.old = self.root / "old" / "analysis" / "wien"
		self.new = self.root / "new" / "analysis" / "wien"
		self.old.mkdir(parents=True)
		self.new.mkdir(parents=True)
		to_metric = Transformer.from_crs(
			"EPSG:4326", "EPSG:31256", always_xy=True
		).transform
		to_wgs = Transformer.from_crs(
			"EPSG:31256", "EPSG:4326", always_xy=True
		).transform
		x, y = to_metric(16.36, 48.22)
		x = math.floor(x / 250) * 250 + 50
		y = math.floor(y / 250) * 250 + 50
		self.old_aoi = self.old / "aoi.geojson"
		self.old_aoi.write_text(
			json.dumps(mapping(transform(to_wgs, box(x, y, x + 20, y + 20)))),
			encoding="utf-8",
		)
		self.old_manifest = self.old / "raster.json"
		write_manifest(
			self.old_manifest, build_manifest(self.old_aoi, size=250, halo=75)
		)
		shutil.copy2(self.old_manifest, self.new / "raster.json")
		shutil.copy2(self.old_aoi, self.new / "aoi.geojson")

	def test_relocation_keeps_manifest_digest_and_geometry(self):
		original_manifest, original_aoi = read_manifest(self.old_manifest)
		new_manifest_file = self.new / "raster.json"
		before = checksum(self.old_manifest)
		shutil.rmtree(self.root / "old")
		migrated_manifest, migrated_aoi = read_manifest(new_manifest_file)
		self.assertEqual(before, checksum(new_manifest_file))
		self.assertEqual(original_manifest, migrated_manifest)
		self.assertTrue(original_aoi.equals_exact(migrated_aoi, tolerance=0))
		self.assertEqual(migrated_manifest["aoi_geojson"], str(self.old_aoi))

	def test_relocation_rejects_changed_aoi(self):
		shutil.rmtree(self.root / "old")
		(self.new / "aoi.geojson").write_text('{"type":"Polygon","coordinates":[]}')
		with self.assertRaisesRegex(ValueError, "AOI-Datei"):
			read_manifest(self.new / "raster.json")

	def test_original_manifest_remains_compatible(self):
		manifest, aoi = read_manifest(self.old_manifest)
		self.assertEqual(len(manifest["tiles"]), 1)
		self.assertGreater(aoi.area, 0)

	def test_new_root_is_explicit_and_not_implicitly_created(self):
		missing = self.root / "does-not-exist"
		result = subprocess.run(
			["bash", "scripts/run-sis-v2-wien.sh"],
			env={"PATH": "/usr/bin:/bin", "SIS_WIEN_ROOT": str(missing)},
			text=True, capture_output=True, check=False,
		)
		self.assertNotEqual(result.returncode, 0)
		self.assertIn("existiert nicht", result.stderr)
		self.assertFalse(missing.exists())


if __name__ == "__main__":
	unittest.main()
