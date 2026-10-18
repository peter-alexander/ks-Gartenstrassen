"""Offline regression tests for the guarded Vienna data relocation."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.consolidate_wien_data import plan, relocate, cleanup


class ConsolidateViennaDataTests(unittest.TestCase):
	def setUp(self):
		tmp = TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.root = Path(tmp.name)
		(self.root / ".git").mkdir()
		files = {
			"data/raw/gip_network_ogd.gpkg": b"GIP RAW",
			"data/raw/FMZK_WIEN_GP.gpkg": b"FMZK RAW",
			"data/wien/wfs-kacheln/a.geojson.xz": b"SIS RAW",
			"data/wien/aoi/wien.geojson": b"Vienna AOI",
			"data/wien/analysis/wien/grm2023/png/tile/part.png": b"GRM RAW",
			"data/wien/sis-wien.sqlite": b"SIS INDEX",
			"data/wien/analysis/wien/gip.sqlite": b"GIP INDEX",
			"data/wien/analysis/wien/raster.json": b"RASTER",
			"data/wien/analysis/wien/aoi.geojson": b"Vienna AOI",
			"data/wien/analysis/wien/ergebnisse/gip_abschnitte.geojson": b'{"type":"FeatureCollection"}',
			"data/wien/analysis/wien/ergebnisse/gip_abschnitte.csv": b"GIP-ID",
			"data/wien/analysis/wien/ergebnisse/bericht.json":
				json.dumps({"gip_ids": 10, "manifest_sha256": "sha"}).encode(),
			"data/wien/analysis/wien/gartenstrassen_sis_v2.pmtiles": b"PMTiles\x03ARCHIVE",
			"data/processed/wienweit/wien/old.dat": b"V0 OLD",
			"data/wien/sis-wien.sqlite.pre-v5-backup": b"OBSOLETE",
		}
		for name, body in files.items():
			path = self.root / name
			path.parent.mkdir(parents=True, exist_ok=True)
			path.write_bytes(body)

	def _move(self):
		with patch("scripts.diagnose_parallel_gip.require_complete_wien",
				return_value={"axes": 20000}):
			relocate(self.root, apply=True)

	def test_default_plan_does_not_modify_anything(self):
		relocate(self.root)
		self.assertTrue((self.root/"data/wien/sis-wien.sqlite").is_file())
		self.assertFalse((self.root/"raw").exists())
		self.assertFalse((self.root/"output").exists())

	def test_resumable_atomic_renames_preserve_downloads_and_outputs(self):
		self._move()
		self.assertEqual((self.root/"raw/gip_network_ogd.gpkg").read_bytes(), b"GIP RAW")
		self.assertEqual((self.root/"raw/grm2023/png/tile/part.png").read_bytes(), b"GRM RAW")
		self.assertEqual((self.root/"raw/sis/wfs-kacheln/a.geojson.xz").read_bytes(), b"SIS RAW")
		self.assertTrue((self.root/"work/wien/gip.sqlite").exists())
		self.assertTrue((self.root/"work/wien/grm2023").is_dir())
		self.assertTrue((self.root/"output/gartenstrassen.pmtiles").exists())
		self.assertFalse((self.root/"data/wien/analysis/wien").exists())
		self.assertTrue(all(status != "verschieben" for _a, _b, status in plan(self.root)))

	def test_collision_blocks_all_moves(self):
		(self.root/"raw").mkdir()
		(self.root/"raw/gip_network_ogd.gpkg").write_bytes(b"COLLISION")
		with self.assertRaises(FileExistsError):
			relocate(self.root, apply=True)
		self.assertTrue((self.root/"data/wien/sis-wien.sqlite").exists())
		self.assertEqual((self.root/"raw/gip_network_ogd.gpkg").read_bytes(), b"COLLISION")

	def test_cleanup_explicit_only_after_valid_outputs(self):
		self._move()
		cleanup(self.root, legacy=True)
		self.assertTrue((self.root/"data/processed/wienweit/wien/old.dat").exists())
		cleanup(self.root, legacy=True, apply=True)
		self.assertFalse((self.root/"data/processed").exists())
		self.assertFalse((self.root/"data/wien").exists())
		self.assertTrue((self.root/"raw/gip_network_ogd.gpkg").exists())
		cleanup(self.root, apply=True)
		self.assertFalse((self.root/"work").exists())
		self.assertTrue((self.root/"output/gartenstrassen.pmtiles").exists())

	def test_cleanup_refuses_incomplete_result(self):
		self._move()
		(self.root/"output/bericht.json").unlink()
		with self.assertRaises(FileNotFoundError):
			cleanup(self.root, legacy=True, apply=True)
		self.assertTrue((self.root/"data/processed").exists())


if __name__ == "__main__":
	unittest.main()
