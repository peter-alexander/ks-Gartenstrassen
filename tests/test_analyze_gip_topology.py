import json
from pathlib import Path
import tempfile
import unittest

from scripts.analyze_gip_topology import audit, run


def line(gid, start, end, coords, name="Testgasse"):
	return {"type": "Feature", "id": f"edge.{gid}",
		"geometry": {"type": "LineString", "coordinates": coords},
		"properties": {"gip_objectid": str(gid), "node_from": start,
			"node_to": end, "name": name, "fow": 3,
			"edgecategory": "G", "dedicatedwidth": -1}}


def node(gid, coord):
	return {"type": "Feature", "id": f"node.{gid}",
		"geometry": {"type": "Point", "coordinates": coord},
		"properties": {"gip_objectid": str(gid), "name": "Knoten"}}


def fixtures():
	axes = [
		line(20, 1, 2, [[16.363, 48.223], [16.3631, 48.223]]),
		line(21, 2, 3, [[16.3631, 48.223], [16.3632, 48.223]]),
		line(30, 10, 11, [[16.365, 48.222], [16.3651, 48.222]],
			"Anderer Weg"),
	]
	nodes = [node(1, [16.363, 48.223]),
		node(2, [16.3631, 48.223]),
		node(3, [16.3632, 48.223]),
		node(10, [16.365, 48.222]),
		node(11, [16.3651, 48.222])]
	probe = {"schema_version": 1,
		"bbox_3857_mit_rand": [1821200, 6143700, 1822100, 6144500],
		"fmzk_bbox_lon_lat": [16.36, 48.221, 16.367, 48.225],
		"datensaetze": {"achsen": {"anzahl": len(axes)},
			"knoten": {"anzahl": len(nodes)}}}
	return axes, nodes, probe


class GIPTopologyTests(unittest.TestCase):
	def test_components_and_endpoints(self):
		axes, nodes, probe = fixtures()
		report = audit(axes, nodes, probe)
		self.assertEqual(report["status"], "topologie_konsistent")
		self.assertEqual(report["endpunkte_mit_knoten"], 6)
		self.assertEqual(report["max_endpunktabweichung_m"], 0)
		self.assertEqual([c["achsen"] for c in report["komponenten"]], [2, 1])
		self.assertEqual(report["dedicatedwidth_fehlt_oder_minus_eins"], 3)

	def test_missing_node_inside_query_is_flagged(self):
		axes, nodes, probe = fixtures()
		nodes = [n for n in nodes if n["properties"]["gip_objectid"] != "2"]
		probe["datensaetze"]["knoten"]["anzahl"] = len(nodes)
		report = audit(axes, nodes, probe)
		self.assertEqual(report["status"], "pruefen")
		self.assertEqual(report["referenzierte_knoten_fehlen"], 1)
		self.assertEqual(len(report["fehlende_knoten_innerhalb_wfs_bbox"]), 2)

	def test_missing_node_outside_query_is_expected(self):
		axes, nodes, probe = fixtures()
		# Knoten 3 liegt ~3 m außerhalb des ostseitigen Suchrandes.
		probe["bbox_3857_mit_rand"][2] = 1821540
		nodes = [n for n in nodes if n["properties"]["gip_objectid"] != "3"]
		probe["datensaetze"]["knoten"]["anzahl"] = len(nodes)
		report = audit(axes, nodes, probe)
		self.assertEqual(report["status"], "topologie_konsistent")
		self.assertEqual(len(report["fehlende_knoten_innerhalb_wfs_bbox"]), 0)
		self.assertEqual(len(report["fehlende_knoten_ausserhalb_wfs_bbox"]), 1)

	def test_mismatched_endpoint_not_silently_snapped(self):
		axes, nodes, probe = fixtures()
		nodes[1]["geometry"]["coordinates"][0] += 0.0001
		report = audit(axes, nodes, probe)
		self.assertEqual(report["status"], "pruefen")
		self.assertEqual(len(report["abweichende_endpunkte"]), 2)
		self.assertGreater(report["max_endpunktabweichung_m"], 1)

	def test_inconsistent_input_is_rejected(self):
		axes, nodes, probe = fixtures()
		probe["datensaetze"]["achsen"]["anzahl"] = 20
		with self.assertRaisesRegex(ValueError, "Anzahl"):
			audit(axes, nodes, probe)
		probe["datensaetze"]["achsen"]["anzahl"] = len(axes)
		nodes.append(nodes[0])
		probe["datensaetze"]["knoten"]["anzahl"] = len(nodes)
		with self.assertRaisesRegex(ValueError, "Doppelte Knoten"):
			audit(axes, nodes, probe)

	def test_local_run_does_not_overwrite(self):
		axes, nodes, probe = fixtures()
		with tempfile.TemporaryDirectory() as temp:
			root = Path(temp)
			(root / "gip_probe_bericht.json").write_text(json.dumps(probe))
			(root / "abschnitte_achsen.geojson").write_text(
				json.dumps({"type": "FeatureCollection", "features": axes}))
			(root / "abschnitte_knoten.geojson").write_text(
				json.dumps({"type": "FeatureCollection", "features": nodes}))
			self.assertEqual(run(root)["anzahl_achsen"], 3)
			with self.assertRaises(FileExistsError):
				run(root)


if __name__ == "__main__":
	unittest.main()
