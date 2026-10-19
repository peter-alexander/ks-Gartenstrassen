"""Publication of grouped GIS data must persist every original GIP edge ID."""
import csv
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.publish_wien import publish
from scripts.wienwide_grid import checksum


class GroupedPublicationTests(unittest.TestCase):
	def test_original_mapping_survives_publication_and_is_hashed(self):
		with TemporaryDirectory() as directory:
			root=Path(directory)
			source=root/"measurement"
			out=root/"output"
			source.mkdir()
			(source/"gip_abschnitte.geojson").write_text(
				'{"type":"FeatureCollection","features":[]}',encoding="utf-8")
			(source/"gip_abschnitte.csv").write_text(
				"gip_id,original_gip_ids\na,a;b\n",encoding="utf-8")
			(source/"bericht.json").write_text(json.dumps({
				"manifest_sha256":"manifest",
				"gip_ids":1,
				"gip_kantenvereinigung":"parallel-gip-groups-v1",
				"geojson_sha256":checksum(source/"gip_abschnitte.geojson"),
				"csv_sha256":checksum(source/"gip_abschnitte.csv"),
			}),encoding="utf-8")
			index=root/"gip_merged.sqlite"
			with sqlite3.connect(index) as db:
				db.execute("""CREATE TABLE merged_members(
					original_id TEXT, representative_id TEXT, role TEXT,
					original_fow INTEGER, original_name TEXT)""")
				db.executemany("INSERT INTO merged_members VALUES (?,?,?,?,?)",[
					("a","a","repraesentant",2,"Allee"),
					("b","a","mitglied",505,"Radweg")])
			def fake_pmtiles(src,dst,*,min_area):
				dst.write_bytes(b"PMTiles\x03test")
				return {"source_sha256":checksum(src),"gip_ids":1,
					"allowed_fow":[2,3,14]}
			with patch("scripts.publish_wien.make_pmtiles",side_effect=fake_pmtiles):
				release=publish(source,out,gip_index=index)
			self.assertIn("gip_kanten_zuordnung.csv",release["files_sha256"])
			with (out/"gip_kanten_zuordnung.csv").open(newline="",encoding="utf-8") as file:
				entries=list(csv.DictReader(file))
			self.assertEqual([row["original_gip_id"] for row in entries],["a","b"])
			self.assertEqual({row["repraesentant_gip_id"] for row in entries},{"a"})
			self.assertEqual(release["files_sha256"]["gip_kanten_zuordnung.csv"],
				checksum(out/"gip_kanten_zuordnung.csv"))
			self.assertTrue((out/"freigabe.json").is_file())

	def test_grouped_publication_refuses_missing_provenance(self):
		with TemporaryDirectory() as directory:
			root=Path(directory)
			source=root/"measurement"
			source.mkdir()
			(source/"gip_abschnitte.geojson").write_text(
				'{"type":"FeatureCollection","features":[]}')
			(source/"gip_abschnitte.csv").write_text("gip_id\na\n")
			(source/"bericht.json").write_text(json.dumps({
				"manifest_sha256":"manifest","gip_ids":1,
				"gip_kantenvereinigung":"parallel-gip-groups-v1",
				"geojson_sha256":checksum(source/"gip_abschnitte.geojson"),
				"csv_sha256":checksum(source/"gip_abschnitte.csv")}))
			with self.assertRaises(FileNotFoundError):
				publish(source,root/"output")
			self.assertFalse((root/"output"/"freigabe.json").exists())


if __name__=="__main__":
	unittest.main()
