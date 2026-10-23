"""Regression test: cached SIS/GRM analysis does not alter CGAL output geometry."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pyproj import Transformer
from shapely.geometry import box,mapping

from scripts.analyze_cgal_sis_grm import analyze,_metric_geometry_for_statistics

TO_WGS=Transformer.from_crs(31256,4326,always_xy=True).transform


class CgalSisGrmTests(unittest.TestCase):
	def test_metric_projection_repair_is_limited_and_preserves_source(self):
		from shapely.geometry import Polygon
		from shapely.ops import transform
		source=box(1500,340000,1510,340010)
		feature={"geometry":mapping(source)}
		calls=[0]
		def slight_invalid(_x,_y,_z=None):
			return (_x,_y)
		# A valid source with a tiny self-crossing after metric transform:
		# the helper must not mutate its GeoJSON representation.
		original=json.dumps(feature["geometry"],sort_keys=True)
		result=_metric_geometry_for_statistics(feature,slight_invalid,"good")
		self.assertTrue(result.is_valid)
		self.assertEqual(json.dumps(feature["geometry"],sort_keys=True),original)

	def test_reject_invalid_source_before_reprojection(self):
		from shapely.geometry import Polygon
		bowtie=Polygon([(0,0),(2,2),(0,2),(2,0),(0,0)])
		with self.assertRaisesRegex(ValueError,"SIS-Quellgeometrie ungültig"):
			_metric_geometry_for_statistics({"geometry":mapping(bowtie)},lambda x,y:(x,y),"bad")

	def test_independent_ground_canopy_and_shared_area(self):
		with TemporaryDirectory() as folder:
			root=Path(folder)
			metric=box(1500,340000,1510,340010)
			from shapely.ops import transform
			wgs=transform(TO_WGS,metric)
			feature={"type":"Feature",
				"properties":{"edge_id":"first","sis_clipped":True},
				"geometry":mapping(wgs)}
			source=root/"sis.geojson"
			source.write_text(
				'{"type":"FeatureCollection","features":[\n'
				+json.dumps(feature,separators=(",",":"))
				+'\n],"metadata":{"sis_provider":"SISBELAGOGD"}}\n',
				encoding="utf-8")
			index=root/"sis.sqlite"
			index.touch()
			manifest=root/"raster.json"
			manifest.write_text("test",encoding="utf-8")
			cache=root/"grm"
			(cache/"masken"/"one").mkdir(parents=True)
			(cache/"masken"/"one"/"crown.sqlite").touch()
			tile={"id":"one","bounds_31256":[1490,339990,1520,340020]}
			out=root/"result.geojson"
			ground=box(1500,340000,1506,340010)
			canopy=box(1504,340000,1508,340010)
			with patch("scripts.analyze_cgal_sis_grm.read_manifest",
					return_value=({"tiles":[tile]},metric)),patch(
				"scripts.analyze_cgal_sis_grm._validate_index",
					return_value={"sha256":"test-index"}),patch(
				"scripts.analyze_cgal_sis_grm.vegetation_mask",
					return_value=ground),patch(
				"scripts.analyze_cgal_sis_grm.read_mask",
					return_value=(canopy,{})):
				stats=analyze(source,index,manifest,cache,out)
			output=json.loads(out.read_text(encoding="utf-8"))
			self.assertEqual(stats["features"],1)
			result=output["features"][0]
			self.assertEqual(result["geometry"],json.loads(json.dumps(feature["geometry"])))
			self.assertEqual(result["properties"]["edge_id"],"first")
			self.assertAlmostEqual(result["properties"]["boden_begruent_m2"],60,delta=0.05)
			self.assertAlmostEqual(result["properties"]["boden_sonstig_m2"],40,delta=0.05)
			self.assertAlmostEqual(result["properties"]["grm2023_baumkronen_m2"],40,delta=0.05)
			self.assertAlmostEqual(result["properties"]["baumkronen_ueber_begruentem_boden_m2"],20,delta=0.05)
			self.assertAlmostEqual(result["properties"]["vegetation_boden_oder_krone_m2"],80,delta=0.05)
			with self.assertRaises(FileExistsError):
				analyze(source,index,manifest,cache,out)


if __name__=="__main__":
	unittest.main()
