"""Standalone WGS84 line export can inspect the grouping without rerunning Vienna."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.export_merged_gip import FILE,META,export
from scripts.merge_parallel_gip import run
from test_merge_parallel_gip import road,synthetic_index


class MergedGIPGeoJSONTests(unittest.TestCase):
	def test_all_original_and_grouped_lines_are_inspectable_and_attested(self):
		with TemporaryDirectory() as directory:
			root=Path(directory)
			source=root/"gip.sqlite"
			merged=root/"gip_merged.sqlite"
			output=root/"output"
			synthetic_index(source,[
				road("a",0),
				road("b",15),
				road("c",500,name="Andere Straße"),
			])
			run(source,merged)
			info=export(merged,output)
			self.assertEqual(info["achsen_gesamt"],2)
			self.assertEqual(info["vereinigte_gruppen"],1)
			self.assertEqual(info["originalkanten_gesamt"],3)
			self.assertTrue((output/FILE).is_file())
			self.assertTrue((output/META).is_file())
			data=json.loads((output/FILE).read_text(encoding="utf-8"))
			self.assertEqual(data["type"],"FeatureCollection")
			self.assertEqual(len(data["features"]),2)
			items={f["properties"]["gip_id"]:f for f in data["features"]}
			self.assertEqual(items["a"]["geometry"]["type"],"MultiLineString")
			self.assertEqual(items["a"]["properties"]["original_gip_ids"],["a","b"])
			self.assertEqual(items["a"]["properties"]["original_fow"],[2,2])
			self.assertEqual(items["a"]["properties"]["anzahl_originalkanten"],2)
			self.assertTrue(items["a"]["properties"]["vereint"])
			self.assertEqual(items["c"]["geometry"]["type"],"LineString")
			self.assertFalse(items["c"]["properties"]["vereint"])
			# Geometrien wurden von metrischen Quellkoordinaten in WGS84
			# transformiert, nicht unverändert als GeoJSON ausgegeben.
			self.assertLess(abs(items["a"]["geometry"]["coordinates"][0][0][0]),180)
			self.assertEqual(export(merged,output),info)

	def test_modified_output_is_not_silently_replaced(self):
		with TemporaryDirectory() as directory:
			root=Path(directory)
			source=root/"gip.sqlite"
			merged=root/"gip_merged.sqlite"
			synthetic_index(source,[road("a",0),road("b",15)])
			run(source,merged)
			out=root/"output"
			export(merged,out)
			(out/FILE).write_text("unmatched previous geometry",encoding="utf-8")
			with self.assertRaisesRegex(ValueError,"vorhandener Export"):
				export(merged,out)
			self.assertEqual((out/FILE).read_text(encoding="utf-8"),
				"unmatched previous geometry")


if __name__=="__main__":
	unittest.main()
