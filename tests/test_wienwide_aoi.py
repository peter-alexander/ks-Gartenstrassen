"""Amtliche Bezirks-AOI-Validierung ohne externen WFS-Aufruf."""
import json
import tempfile
from pathlib import Path
import unittest

from shapely.geometry import box, mapping, shape
from shapely import union_all
from scripts.wienwide_aoi import (
	source_url,read_boundaries,create_aois,
)


def sample():
	features=[]
	for number in range(1,24):
		x=16.2+.01*(number-1)
		y=48.15
		features.append({"type":"Feature","id":f"bezirk.{number}",
			"properties":{"BEZNR":number,"NAMEK":f"Bezirk {number}"},
			"geometry":mapping(box(x,y,x+.009,y+.008))})
	return {"type":"FeatureCollection","features":features,
		"totalFeatures":23}


class DistrictAOITests(unittest.TestCase):
	def test_official_layer_url_and_23_unique_numbers(self):
		self.assertIn("BEZIRKSGRENZEOGD",source_url())
		data=read_boundaries(json.dumps(sample()).encode())
		self.assertEqual(len(data),23)
		self.assertEqual(data[9]["name"],"Bezirk 9")

	def test_writes_requested_districts_and_union_without_overwrite(self):
		with tempfile.TemporaryDirectory() as directory:
			root=Path(directory)
			raw=json.dumps(sample()).encode()
			report=create_aois(raw,root,numbers=[22,9],whole_city=True)
			self.assertEqual(len(report["ausgaben"]),3)
			self.assertEqual(report["wfs_features"],23)
			for n in (9,22):
				doc=json.loads((root/f"bezirk_{n:02d}.geojson").read_text())
				self.assertEqual(doc["features"][0]["properties"]["bezirk"],n)
				self.assertTrue(shape(doc["features"][0]["geometry"]).is_valid)
			full=json.loads((root/"wien.geojson").read_text())
			geom=shape(full["features"][0]["geometry"])
			expected=union_all([shape(f["geometry"])
				for f in sample()["features"]])
			self.assertAlmostEqual(geom.area,expected.area,places=10)
			with self.assertRaises(FileExistsError):
				create_aois(raw,root,numbers=[9])

	def test_rejects_missing_district_wrong_crs_and_incomplete_wfs(self):
		data=sample();data["features"].pop()
		with self.assertRaisesRegex(ValueError,"Unvollständige Bezirks-WFS"):
			read_boundaries(json.dumps(data).encode())
		data=sample();data["features"].pop();data.pop("totalFeatures")
		with self.assertRaisesRegex(ValueError,"nicht vollständig"):
			read_boundaries(json.dumps(data).encode())
		data=sample();data["features"][1]["properties"]["BEZNR"]=1
		with self.assertRaisesRegex(ValueError,"mehrfach"):
			read_boundaries(json.dumps(data).encode())
		data=sample()
		data["crs"]={"type":"name","properties":{"name":"EPSG:3857"}}
		with self.assertRaisesRegex(ValueError,"Quell-CRS"):
			read_boundaries(json.dumps(data).encode())


if __name__=="__main__":
	unittest.main()
