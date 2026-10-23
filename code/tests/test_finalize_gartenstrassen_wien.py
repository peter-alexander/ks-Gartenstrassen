import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pyproj import Transformer
from shapely.geometry import box,mapping
from shapely.ops import transform

from scripts.finalize_gartenstrassen_wien import _audit_and_write_ndjson


TO_WGS=Transformer.from_crs(31256,4326,always_xy=True).transform


class FinalizationAuditTests(unittest.TestCase):
	def test_audit_preserves_edge_id_and_emits_numeric_stable_id(self):
		with TemporaryDirectory() as folder:
			root=Path(folder)
			metric=box(1500,340000,1510,340010)
			feature={"type":"Feature","properties":{
				"edge_id":"a-valid-original-edge","area_m2":100.,
				"boden_begruent_m2":60.,"grm2023_baumkronen_m2":40.,
				"baumkronen_ueber_begruentem_boden_m2":20.,
				"vegetation_boden_oder_krone_m2":80.,
				"boden_begruent_pct":60.,
				"grm2023_baumkronen_pct":40.,
				"vegetation_boden_oder_krone_pct":80.,
			},"geometry":mapping(transform(TO_WGS,metric))}
			source=root/"input.geojson"
			source.write_text(
				'{"type":"FeatureCollection","features":[\n'
				+json.dumps(feature,separators=(",",":"))
				+'\n],"metadata":{"schema":"cgal-sis-grm-ground-v1","sis_provider":"SISBELAGOGD"}}\n',
				encoding="utf-8")
			ndjson=root/"tiles.ndjson"
			report=_audit_and_write_ndjson(source,ndjson)
			out=json.loads(ndjson.read_text(encoding="utf-8"))
			self.assertEqual(report["features"],1)
			self.assertEqual(report["positive_area_overlaps_count"],0)
			self.assertEqual(out["properties"]["edge_id"],"a-valid-original-edge")
			self.assertEqual(out["properties"]["boden_begruent_pct"],60.)
			self.assertEqual(out["properties"]["grm2023_baumkronen_pct"],40.)
			self.assertIsInstance(out["id"],int)
			self.assertEqual(out["id"],out["properties"]["feature_id"])


if __name__=="__main__":
	unittest.main()
