"""Fresh Wiener run: cleanup never touches permanent downloads or outputs."""
import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from scripts.clean_wien_work import clean, checksum, verify
from scripts.sis_gip2 import read_only


class CleanWienWorkTests(unittest.TestCase):
	def setUp(self):
		self.tmp = TemporaryDirectory()
		self.addCleanup(self.tmp.cleanup)
		self.root = Path(self.tmp.name)
		out = self.root / "output"
		work = self.root / "work" / "wien"
		raw = self.root / "raw"
		out.mkdir()
		work.mkdir(parents=True)
		raw.mkdir()
		(raw / "source.txt").write_text("unaltered", encoding="utf-8")
		(work / "raster.json").write_text('{"tiles": []}', encoding="utf-8")
		(work / "intermediate.db").write_bytes(b"REGENERABLE")
		(out / "gartenstrassen.pmtiles").write_bytes(b"PMTiles\x03" + b"archive")
		(out / "gip_abschnitte.geojson").write_text(
			'{"type":"FeatureCollection","features":[]}', encoding="utf-8")
		with (out / "gip_abschnitte.csv").open("w", newline="", encoding="utf-8") as f:
			writer = csv.writer(f)
			writer.writerow(["gip_id", "fow", "abschnitt_flaeche_m2"])
			for i in range(10000):
				writer.writerow([i, 3, 100])
		(out / "bericht.json").write_text(json.dumps({
			"gip_ids": 10000,
			"manifest_sha256": checksum(work / "raster.json"),
		}), encoding="utf-8")

	def test_preview_never_deletes(self):
		self.assertEqual(verify(self.root)["gip_ids"], 10000)
		clean(self.root)
		self.assertTrue((self.root / "work" / "wien" / "intermediate.db").exists())

	def test_explicit_apply_deletes_only_work(self):
		clean(self.root, apply=True)
		self.assertFalse((self.root / "work").exists())
		self.assertEqual((self.root / "raw" / "source.txt").read_text(), "unaltered")
		self.assertTrue((self.root / "output" / "gartenstrassen.pmtiles").exists())

	def test_wrong_manifest_prevents_deletion(self):
		(self.root / "work" / "wien" / "raster.json").write_text("changed")
		with self.assertRaisesRegex(ValueError, "stimmen nicht überein"):
			clean(self.root, apply=True)
		self.assertTrue((self.root / "work" / "wien").exists())

	def test_invalid_archive_prevents_deletion(self):
		(self.root / "output" / "gartenstrassen.pmtiles").write_bytes(b"garbage")
		with self.assertRaisesRegex(ValueError, "PMTiles"):
			clean(self.root, apply=True)
		self.assertTrue((self.root / "work" / "wien").exists())

	def test_immutable_sqlite_reader_no_write_or_sidecar(self):
		source = self.root / "source.gpkg"
		with sqlite3.connect(source) as db:
			db.execute("CREATE TABLE gpkg_contents (name TEXT)")
		with read_only(source) as db:
			self.assertIsNotNone(db.execute("SELECT name FROM sqlite_master").fetchone())
			with self.assertRaises(sqlite3.OperationalError):
				db.execute("CREATE TABLE should_fail (id INT)")
		self.assertEqual(sorted(p.name for p in self.root.iterdir()),
			["output", "raw", "source.gpkg", "work"])


if __name__ == "__main__":
	unittest.main()
