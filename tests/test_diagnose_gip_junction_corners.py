import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pyproj import Transformer
from shapely import union_all
from shapely.geometry import LineString, Point, box, mapping
from shapely.ops import transform

from scripts.diagnose_gip_junction_corners import (
	METRIC, LONLAT, _profile, analyze, fahrbahn_mask, run,
)


def synthetic_cross(*, east_west_halfwidth=4, north_south_halfwidth=4):
	# Geometry in a plausible Vienna-local EPSG:31256 frame.
	x, y = METRIC(16.363, 48.223)
	street = union_all([
		box(x-50, y-east_west_halfwidth, x+50, y+east_west_halfwidth),
		box(x-north_south_halfwidth, y-50, x+north_south_halfwidth, y+50),
	])
	center = Point(x, y)
	directions = [(60, 0), (-60, 0), (0, 60), (0, -60)]
	nodes = [{"type": "Feature", "properties": {
		"gip_objectid": "10", "name": "Ideale Kreuzung"},
		"geometry": mapping(transform(LONLAT, center))}]
	axes = []
	for idx, (dx, dy) in enumerate(directions, start=1):
		end = Point(x+dx, y+dy)
		end_id = str(idx+10)
		nodes.append({"type": "Feature", "properties": {
			"gip_objectid": end_id, "name": "Randknoten"},
			"geometry": mapping(transform(LONLAT, end))})
		axes.append({"type": "Feature", "properties": {
			"gip_objectid": str(idx), "name": f"Testgasse {idx}",
			"node_from": "10", "node_to": end_id, "fow": 3},
			"geometry": mapping(transform(LONLAT, LineString([center, end])))})
	return street, axes, nodes


class JunctionCornerDiagnosticsTests(unittest.TestCase):
	def test_ideal_cross_produces_profiles_corner_candidates_and_cuts(self):
		street, axes, nodes = synthetic_cross()
		layers, report = analyze(street, axes, nodes,
			node_ids=["10"], max_junctions=1)
		self.assertEqual(len(report["knoten"]), 1)
		self.assertEqual(report["knoten"][0]["degree"], 4)
		self.assertGreater(len(layers["querprofile"]), 25)
		# A perpendicular road can exceed the diagnostic cross-section:
		# it must still serve as evidence of widening, not erase it.
		self.assertGreaterEqual(
			len(layers["schnittlinien"]), 2)
		self.assertGreaterEqual(
			len(layers["eckpunkte"]), 4)
		self.assertIn("kandidat_pruefen", report["arm_status_counts"])
		self.assertTrue(all(f["properties"]["status"] != "validiert"
			for f in layers["schnittlinien"]))

	def test_t_junction_one_sided_transition_has_orthogonal_cut(self):
		street, axes, nodes = synthetic_cross()
		x, y = METRIC(16.363, 48.223)
		# Gerade durchgehende Straße und nach Norden einmündender Arm:
		# südlicher Gehsteig-/Gebäuderand bleibt auf beiden Hauptarmen
		# unverändert, nur die Nordseite weitet sich auf.
		street = union_all([
			box(x-50, y-5, x+50, y+5),
			box(x-4, y, x+4, y+50),
		])
		axes = axes[:3]
		layers, report = analyze(street, axes, nodes,
			node_ids=["10"], max_junctions=1)
		orthogonal = [f for f in layers["schnittlinien"]
			if f["properties"]["methode"] == "orthogonal_einseitig"]
		self.assertGreaterEqual(len(orthogonal), 1)
		for feature in orthogonal:
			line = transform(METRIC, LineString(feature["geometry"]["coordinates"]))
			self.assertTrue(line.within(street.buffer(.05)))
			self.assertEqual(feature["properties"]["left_s_m"],
				feature["properties"]["right_s_m"])
		self.assertGreaterEqual(
			sum(p["properties"]["status"].startswith("orthogonaler")
				for p in layers["eckpunkte"]), 1)
		self.assertEqual(report["parameter"]["boundary_mode"], "hauswand")

	def test_fahrbahn_mode_is_explicit_and_does_not_replace_street_mask(self):
		street, axes, nodes = synthetic_cross()
		x, y = METRIC(16.363, 48.223)
		# Fahrbahn ist schmäler als die äußere Straßenraumgrenze.
		fahrbahn = union_all([
			box(x-50, y-3, x+50, y+3),
			box(x-3, y-50, x+3, y+50),
		])
		data = [(1, 21, "Fahrbahn", fahrbahn),
			(2, 23, "Gehsteig", street.difference(fahrbahn))]
		curb = fahrbahn_mask(data, street)
		self.assertAlmostEqual(curb.area, fahrbahn.area, places=5)
		self.assertLess(curb.area, street.area)
		layers, report = analyze(curb, axes, nodes,
			node_ids=["10"], max_junctions=1,
			boundary_mode="gehsteigkante")
		self.assertEqual(report["parameter"]["boundary_mode"], "gehsteigkante")
		self.assertTrue(all(f["properties"]["grenzmodus"] == "gehsteigkante"
			for f in layers["schnittlinien"]))
		with self.assertRaisesRegex(ValueError, "Fahrbahnklasse"):
			fahrbahn_mask([(2, 23, "Gehsteig", street)], street)
		with self.assertRaisesRegex(ValueError, "Grenzmodus"):
			analyze(street, axes, nodes, node_ids=["10"], max_junctions=1,
				boundary_mode="unbekannt")

	def test_straight_road_does_not_invent_crossing_corners(self):
		street, axes, nodes = synthetic_cross()
		x, y = METRIC(16.363, 48.223)
		# Replace cross with one long strip, still a 4-way GIP junction:
		# the geometric evidence of an intersection is missing.
		straight = box(x-50, y-5, x+50, y+5)
		layers, report = analyze(straight, axes, nodes,
			node_ids=["10"], max_junctions=1)
		self.assertEqual(len(layers["schnittlinien"]), 0)
		self.assertNotIn("kandidat_pruefen", report["arm_status_counts"])

	def test_short_arms_and_special_links_are_explicit(self):
		street, axes, nodes = synthetic_cross()
		axes[0]["properties"]["fow"] = 15
		# Second axis is only 10 m between adjacent nodes.
		start = Point(*METRIC(16.363, 48.223))
		end = Point(start.x-10, start.y)
		axes[1]["geometry"] = mapping(transform(LONLAT,
			LineString([start, end])))
		nodes[2]["geometry"] = mapping(transform(LONLAT, end))
		layers, report = analyze(street, axes, nodes,
			node_ids=["10"], max_junctions=1)
		status = [arm["status"] for arm in report["knoten"][0]["arme"]]
		self.assertIn("sonderachse_fow", status)
		self.assertIn("arm_zu_kurz", status)

	def test_unknown_and_duplicate_requested_nodes_are_rejected(self):
		street, axes, nodes = synthetic_cross()
		for ids in (["wrong"], ["10", "10"]):
			with self.subTest(ids=ids), self.assertRaises(ValueError):
				analyze(street, axes, nodes, node_ids=ids,
					max_junctions=2)
		with self.assertRaisesRegex(ValueError, "Parameter"):
			analyze(street, axes, nodes, node_ids=["10"],
				max_junctions=1, step_m=0.01)

	def test_repeated_selection_and_diagnosis_are_deterministic(self):
		street, axes, nodes = synthetic_cross()
		a, report_a = analyze(street, axes, nodes,
			node_ids=["10"], max_junctions=1)
		b, report_b = analyze(street, axes, nodes,
			node_ids=["10"], max_junctions=1)
		self.assertEqual(a, b)
		self.assertEqual(report_a["arm_status_counts"],
			report_b["arm_status_counts"])

	def test_no_existing_diagnosis_is_overwritten(self):
		street, axes, nodes = synthetic_cross()
		with tempfile.TemporaryDirectory() as temp:
			root = Path(temp)
			root.mkdir(exist_ok=True)
			(root/"kreuzungen_diagnose_bericht.json").write_text("{}")
			with self.assertRaises(FileExistsError):
				run(output=root)


if __name__ == "__main__":
	unittest.main()
