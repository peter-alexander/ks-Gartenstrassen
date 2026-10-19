"""Deterministic delta-debug tests without native Boost runs."""
import tempfile
import unittest
from pathlib import Path
import json

from scripts.diagnose_boost_voronoi import minimize, _candidate_geojson


class BoostDiagnosisTests(unittest.TestCase):
	def test_isolates_one_problematic_additional_segment(self):
		base=[("base",)]
		extra=[("x",i) for i in range(8)]
		def tester(keys,_frame):
			return {"status":"timeout" if ("x",5) in keys else "ok",
				"wall_s":0.01}
		suspect,history,reason=minimize(base,extra,None,tester,max_tests=50)
		self.assertEqual(suspect,[("x",5)])
		self.assertEqual(reason,"single_segment_with_base")
		self.assertTrue(history)

	def test_combined_interaction_keeps_required_pair(self):
		base=[]
		extra=[("x",i) for i in range(6)]
		def tester(keys,_frame):
			return {"status":"timeout" if ("x",1) in keys and ("x",4) in keys
				else "ok","wall_s":0.01}
		suspect,history,reason=minimize(base,extra,None,tester,max_tests=80)
		self.assertEqual(set(suspect),{("x",1),("x",4)})
		self.assertEqual(reason,"interaction_or_threshold")

	def test_budget_stops_deterministically(self):
		extra=[("x",i) for i in range(10)]
		def tester(keys,_frame):
			return {"status":"timeout","wall_s":0.01}
		_,history,reason=minimize([],extra,None,tester,max_tests=1)
		self.assertEqual(len(history),1)
		self.assertEqual(reason,"test_budget")

	def test_debug_geojson_has_owners_and_groups(self):
		a=((0,0),(1000,0))
		b=((0,1000),(1000,1000))
		with tempfile.TemporaryDirectory() as tmp:
			path=Path(tmp)/"suspects.geojson"
			_candidate_geojson(path,[a],[b],{a:"a",b:"b"},(100,200))
			doc=json.loads(path.read_text(encoding="utf-8"))
			self.assertEqual(len(doc["features"]),2)
			self.assertEqual([f["properties"]["group"] for f in doc["features"]],
				["base","suspect"])
			self.assertEqual(doc["features"][0]["geometry"]["coordinates"],
				[[100.0,200.0],[101.0,200.0]])


if __name__=="__main__":
	unittest.main()
