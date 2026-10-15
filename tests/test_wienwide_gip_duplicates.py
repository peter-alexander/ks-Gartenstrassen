"""GIP duplicates: only exactly matching repeated features may be discarded.

Tests operate exclusively on synthetic cached feature views. No network.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.wienwide_gip import (
	AXES, NODES, REPORT, deduplicate_tile_view, diagnose_id,
)
from scripts.wienwide_grid import checksum


def axis(gid, *, coordinates=None, fow=3, name="Pilotstraße", wfs_id="wfs.1"):
	return {
		"type": "Feature", "id": wfs_id,
		"geometry": {
			"type": "LineString", "coordinates": coordinates or
				[[16.35, 48.22], [16.351, 48.221]],
		},
		"properties": {
			"gip_objectid": str(gid), "name": name,
			"node_from": 123, "node_to": 456, "fow": fow,
			"frc": 4, "wfs_id": wfs_id,
			"status": "nur_quellgeometrie_ungepruefte_abschnittsflaeche",
		},
	}


def node(gid, *, x=16.35, wfs_id="node.1"):
	return {
		"type": "Feature", "id": wfs_id,
		"geometry": {"type": "Point", "coordinates": [x, 48.22]},
		"properties": {
			"gip_objectid": str(gid), "name": "Knoten",
			"wfs_id": wfs_id,
		},
	}


class WienwideGipDuplicateTests(unittest.TestCase):
	def test_identical_axis_in_single_tile_is_safe_to_collapse(self):
		a = axis(10026184)
		b = axis(10026184, wfs_id="wfs.2")
		unique, duplicates = deduplicate_tile_view(
			[a, b, axis(222, wfs_id="wfs.3")],
			kind="achsen", tile_id="x+000001_y+000341")
		self.assertEqual([x["properties"]["gip_objectid"] for x in unique],
			["10026184", "222"])
		self.assertEqual(duplicates, 1)
		self.assertEqual(a["geometry"], unique[0]["geometry"])

	def test_same_id_different_geometry_is_not_silently_merged(self):
		a = axis(10026184)
		b = axis(10026184,
			coordinates=[[16.35, 48.22], [16.352, 48.221]])
		with self.assertRaisesRegex(ValueError,
			"10026184.*Geometrie identisch: False"):
			deduplicate_tile_view([a, b],
				kind="achsen", tile_id="first")

	def test_same_id_changed_graph_attribute_is_rejected(self):
		a = axis(10026184)
		b = axis(10026184, fow=4)
		with self.assertRaisesRegex(ValueError,
			"Attribute abweichend: .*fow"):
			deduplicate_tile_view([a, b],
				kind="achsen", tile_id="first")

	def test_nodes_are_checked_too(self):
		a = node(111)
		b = node(111, wfs_id="node.2")
		items, n = deduplicate_tile_view(
			[a, b], kind="knoten", tile_id="first")
		self.assertEqual(n, 1)
		self.assertEqual(len(items), 1)
		with self.assertRaisesRegex(ValueError, "Geometrie identisch: False"):
			deduplicate_tile_view([a, node(111, x=16.36)],
				kind="knoten", tile_id="first")

	def test_diagnostic_reads_verified_local_caches_without_changing_them(self):
		with TemporaryDirectory() as tmp:
			root = Path(tmp)
			for tid in ("tile_a", "tile_b"):
				folder = root / tid
				folder.mkdir()
				axes = [axis(10026184, wfs_id=f"{tid}.1")]
				if tid == "tile_a":
					axes.append(axis(10026184, wfs_id=f"{tid}.2"))
				for name, features in ((AXES, axes), (NODES, [node(7)])):
					(folder / name).write_text(json.dumps({
						"type": "FeatureCollection", "features": features,
					}), encoding="utf-8")
				(folder / REPORT).write_text(json.dumps({
					"tile_id": tid,
					"sha256": {
						"achsen": checksum(folder / AXES),
						"knoten": checksum(folder / NODES),
					},
				}), encoding="utf-8")
			with patch("scripts.wienwide_gip.read_manifest",
				return_value=({"tiles": [
					{"id": "tile_a"}, {"id": "tile_b"},
				]}, None)):
				report = diagnose_id(root / "manifest.json", root, "10026184")
			self.assertEqual(report["vorkommen"], 3)
			self.assertEqual(report["betroffene_kacheln"], ["tile_a", "tile_b"])
			self.assertEqual(len({r["geometry_wkt"] for r in report["fundstellen"]}), 1)


if __name__ == "__main__":
	unittest.main()
