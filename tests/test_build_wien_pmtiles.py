"""Unabhängige QA und PMTiles-Build (ohne externe Tippecanoe-Installation)."""
import csv
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from shapely.geometry import box, mapping

from scripts.build_wien_pmtiles import (
	_features, validate_source, build, LAYER,
)
from scripts.wienwide_gip_greening import CSV_COLUMNS


class WienPmtilesTests(unittest.TestCase):
	def setUp(self):
		self.temp=TemporaryDirectory()
		self.addCleanup(self.temp.cleanup)
		self.directory=Path(self.temp.name)
		self.rows=[
			{"gip_id":"10023274","strassenname":"A-Straße",
				"fow":"3","abschnitt_flaeche_m2":"120",
				"boden_m2":"12","boden_pct":"10",
				"boden_58_m2":"12","boden_69_m2":"0",
				"boden_klassen_ueberlagerung_m2":"0",
				"grm_kronen_m2":"60","grm_kronen_pct":"50",
				"kachelteile":"2"},
			{"gip_id":"10023323","strassenname":"B-Straße",
				"fow":"3","abschnitt_flaeche_m2":"150",
				"boden_m2":"0","boden_pct":"0",
				"boden_58_m2":"0","boden_69_m2":"0",
				"boden_klassen_ueberlagerung_m2":"0",
				"grm_kronen_m2":"","grm_kronen_pct":"",
				"kachelteile":"1"},
		]
		with (self.directory/"gip_abschnitte.csv").open(
				"w",encoding="utf-8",newline="") as dst:
			w=csv.DictWriter(dst,fieldnames=CSV_COLUMNS)
			w.writeheader()
			w.writerows(self.rows)
		self.features=[]
		for row,geometry in zip(self.rows,[
				box(16.35,48.20,16.36,48.21),
				box(16.37,48.22,16.38,48.23)]):
			props={}
			for k,v in row.items():
				if k in {"fow","kachelteile"}:
					props[k]=int(v)
				elif k in {"gip_id","strassenname"}:
					props[k]=v
				else:
					props[k]=float(v) if v else None
			self.features.append({
				"type":"Feature","id":row["gip_id"],
				"properties":props,
				"geometry":mapping(geometry),
			})
		(self.directory/"gip_abschnitte.geojson").write_text(
			json.dumps({"type":"FeatureCollection",
				"features":self.features},ensure_ascii=False,
				separators=(",",":"))+"\n",encoding="utf-8")
		(self.directory/"export_bericht.json").write_text(json.dumps({
			"schema_version":1,"min_area_m2":100.,
			"full_gip_ids":3,"output_gip_ids":2,"omitted_gip_ids":1,
			"wgs84_projection_repair_count":0,
		}),encoding="utf-8")

	def _write_features(self):
		(self.directory/"gip_abschnitte.geojson").write_text(
			json.dumps({"type":"FeatureCollection",
				"features":self.features},ensure_ascii=False,
				separators=(",",":"))+"\n",encoding="utf-8")

	def test_source_validation_does_not_change_originals(self):
		file=self.directory/"gip_abschnitte.geojson"
		before=file.read_bytes()
		result=validate_source(self.directory)
		self.assertEqual(result["gip_ids"],2)
		self.assertEqual(file.read_bytes(),before)
		self.assertEqual(
			[f["id"] for f in _features(file)],
			["10023274","10023323"])

	def test_geojson_attribute_mismatch_aborts(self):
		self.features[1]["properties"]["grm_kronen_pct"]=0
		self._write_features()
		with self.assertRaisesRegex(ValueError,
			"Attribut grm_kronen_pct nicht NULL"):
			validate_source(self.directory)

	def test_geojson_duplicate_id_aborts(self):
		self.features[1]["id"]="10023274"
		self._write_features()
		with self.assertRaisesRegex(ValueError,
			"GIP-ID fehlt/doppelt/unbekannt"):
			validate_source(self.directory)

	def test_missing_feature_aborts(self):
		self.features.pop()
		self._write_features()
		with self.assertRaisesRegex(ValueError,"GeoJSON unvollständig"):
			validate_source(self.directory)

	def test_bad_or_trailing_json_aborts(self):
		path=self.directory/"gip_abschnitte.geojson"
		path.write_text(path.read_text()+"false",encoding="utf-8")
		with self.assertRaisesRegex(ValueError,"unerwarteter Inhalt"):
			validate_source(self.directory)

	def _fake_run(self,args,**kwargs):
		if args[1]=="--version":
			return subprocess.CompletedProcess(args,0,
				stdout="tippecanoe v2.75.0\n",stderr="")
		if "verify" in args:
			return subprocess.CompletedProcess(args,0)
		self.assertIn("--use-attribute-for-id=gip_id",args)
		self.assertIn("--convert-stringified-ids-to-numbers",args)
		self.assertIn("--no-feature-limit",args)
		self.assertIn("--no-tile-size-limit",args)
		self.assertIn("--simplify-only-low-zooms",args)
		self.assertIn("--no-tiny-polygon-reduction",args)
		self.assertIn("--minimum-zoom",args)
		self.assertIn("--maximum-zoom",args)
		self.assertEqual(args[-1],
			str(self.directory/"gip_abschnitte.geojson"))
		dest=Path(args[args.index("--output")+1])
		self.assertEqual(dest.name,f"{LAYER}.tmp.pmtiles")
		dest.write_bytes(b"PMTiles\x03"+b"\0"*128)
		return subprocess.CompletedProcess(args,0)

	def test_atomic_build_and_manifest(self):
		with patch("scripts.build_wien_pmtiles.subprocess.run",
				side_effect=self._fake_run):
			report=build(self.directory,tippecanoe="tippecanoe",
				pmtiles="pmtiles")
		self.assertEqual(report["input_features"],2)
		self.assertTrue(report["archive_structural_verify"])
		self.assertEqual(report["zoom_min"],12)
		self.assertEqual(report["zoom_max"],17)
		self.assertEqual(report["layer"],LAYER)
		self.assertTrue((self.directory/f"{LAYER}.pmtiles").exists())
		self.assertTrue((self.directory/"pmtiles_bericht.json").exists())
		self.assertFalse(
			(self.directory/f"{LAYER}.tmp.pmtiles").exists())
		self.assertEqual(json.loads(
			(self.directory/"pmtiles_bericht.json").read_text())["input_features"],2)
		with self.assertRaises(FileExistsError):
			build(self.directory,tippecanoe="tippecanoe")

	def test_external_build_failure_leaves_source_intact(self):
		file=self.directory/"gip_abschnitte.geojson"
		before=file.read_bytes()
		def failing(args,**kwargs):
			if args[1]=="--version":
				return subprocess.CompletedProcess(args,0,
					stdout="tippecanoe v2.75.0\n",stderr="")
			Path(args[args.index("--output")+1]).write_bytes(
				b"partial")
			raise subprocess.CalledProcessError(1,args)
		with patch("scripts.build_wien_pmtiles.subprocess.run",
				side_effect=failing):
			with self.assertRaises(subprocess.CalledProcessError):
				build(self.directory,tippecanoe="tippecanoe")
		self.assertEqual(file.read_bytes(),before)
		self.assertFalse((self.directory/f"{LAYER}.pmtiles").exists())
		self.assertFalse((self.directory/f"{LAYER}.tmp.pmtiles").exists())
		self.assertFalse((self.directory/"pmtiles_bericht.json").exists())

	def test_invalid_pmtiles_magic_cannot_be_published(self):
		def fake(args,**kwargs):
			if args[1]=="--version":
				return subprocess.CompletedProcess(args,0,
					stdout="tippecanoe v2.75.0\n",stderr="")
			Path(args[args.index("--output")+1]).write_bytes(
				b"not-pmtiles"*100)
			return subprocess.CompletedProcess(args,0)
		with patch("scripts.build_wien_pmtiles.subprocess.run",
				side_effect=fake):
			with self.assertRaisesRegex(ValueError,"kein gültiges PMTiles"):
				build(self.directory,tippecanoe="tippecanoe")
		self.assertFalse((self.directory/f"{LAYER}.pmtiles").exists())

	def test_old_tippecanoe_is_rejected_without_output(self):
		with patch("scripts.build_wien_pmtiles.subprocess.run",
				return_value=subprocess.CompletedProcess(
					[],0,stdout="tippecanoe v2.16.0",stderr="")):
			with self.assertRaisesRegex(ValueError,">= 2.17"):
				build(self.directory,tippecanoe="tippecanoe")
		self.assertFalse((self.directory/f"{LAYER}.pmtiles").exists())


if __name__=="__main__":
	unittest.main()
