"""GIP duplicates: only exactly matching repeated features may be discarded.

Tests operate exclusively on synthetic cached feature views. No network.
"""
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pyproj import Transformer
from shapely.geometry import box

from scripts.wienwide_gip import (
	AXES, NODES, REPORT, deduplicate_tile_view, diagnose_id, build_index,
)
from scripts.wienwide_grid import checksum


def axis(gid, *, coordinates=None, fow=3, name="Pilotstraße", wfs_id="wfs.1", route=None):
	return {
		"type": "Feature", "id": wfs_id,
		"geometry": {
			"type": "LineString", "coordinates": coordinates or
				[[16.35, 48.22], [16.351, 48.221]],
		},
		"properties": {
			"gip_objectid": str(gid), "name": name,
			"node_from": 123, "node_to": 456, "fow": fow,
			"frc": 4, "wfs_id": wfs_id, "reg_strname": route,
			"status": "nur_quellgeometrie_ungepruefte_abschnittsflaeche",
		},
	}


def node(gid, *, x=16.35, y=48.22, wfs_id="node.1"):
	return {
		"type": "Feature", "id": wfs_id,
		"geometry": {"type": "Point", "coordinates": [x, y]},
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


	def test_same_physical_axis_can_carry_two_wfs_route_names(self):
		# Realer Diagnosefall: Brunner Straße, GIP 10026184,
		# in benachbarten Kacheln zweimal als B12 bzw. B13a.
		features = [
			axis(10026184, name="Brunner Straße",
				wfs_id="STRASSENGRAPHOGD.61196089", route="B12"),
			axis(10026184, name="Brunner Straße",
				wfs_id="STRASSENGRAPHOGD.61196034", route="B13a"),
		]
		from collections import Counter
		audit = Counter()
		unique, duplicates = deduplicate_tile_view(features,
			kind="achsen", tile_id="x-000003_y+000333", audit=audit)
		self.assertEqual(duplicates, 1)
		self.assertEqual(len(unique), 1)
		self.assertEqual(unique[0]["properties"]["reg_strname"], "B12")
		self.assertEqual(audit["routenvarianten_in_kachel"], 1)

	def test_route_exception_does_not_allow_other_changed_properties(self):
		a = axis(10026184, wfs_id="STRASSENGRAPHOGD.61196089",
			route="B12")
		b = axis(10026184, wfs_id="STRASSENGRAPHOGD.61196034",
			route="B13a")
		b["properties"]["node_to"] = 999
		with self.assertRaisesRegex(ValueError,
			"Attribute abweichend: .*node_to"):
			deduplicate_tile_view([a, b], kind="achsen",
				tile_id="x-000003_y+000333")
		b["properties"]["node_to"] = 456
		b["geometry"]["coordinates"][-1] = [16.351, 48.222]
		with self.assertRaisesRegex(ValueError,
			"Geometrie identisch: False"):
			deduplicate_tile_view([a, b], kind="achsen",
				tile_id="x-000003_y+000333")

	def test_two_routes_in_two_tiles_create_one_physical_axis(self):
		with TemporaryDirectory() as tmp:
			root = Path(tmp)
			manifest_path = root / "raster.json"
			manifest_path.write_text("synthetic verified AOI", encoding="utf-8")
			tiles = ["x-000003_y+000333", "x-000003_y+000334"]
			original = [
				axis(10026184, name="Brunner Straße", route="B12",
					wfs_id="STRASSENGRAPHOGD.61196089"),
				axis(10026184, name="Brunner Straße", route="B13a",
					wfs_id="STRASSENGRAPHOGD.61196034"),
			]
			nodes = [
				node(123, x=16.35, y=48.22, wfs_id="knoten.123"),
				node(456, x=16.351, y=48.221, wfs_id="knoten.456"),
			]
			for tid in tiles:
				folder = root / "gip_fragmente" / tid
				folder.mkdir(parents=True)
				for filename, features in ((AXES, original), (NODES, nodes)):
					(folder / filename).write_text(json.dumps({
						"type": "FeatureCollection", "features": features,
					}), encoding="utf-8")
				(folder / REPORT).write_text(json.dumps({
					"schema_version": 1, "tile_id": tid,
					"max_features": 4000,
					"urls": {"achsen": "a", "knoten": "n"},
					"sha256": {
						"achsen": checksum(folder / AXES),
						"knoten": checksum(folder / NODES),
					},
				}), encoding="utf-8")
			to_metric = Transformer.from_crs("EPSG:4326", "EPSG:31256",
				always_xy=True)
			x1, y1 = to_metric.transform(16.35, 48.22)
			x2, y2 = to_metric.transform(16.351, 48.221)
			aoi = box(min(x1, x2)-10, min(y1, y2)-10,
				max(x1, x2)+10, max(y1, y2)+10)
			manifest = {"tiles": [{"id": tid} for tid in tiles],
				"halo_m": 75}
			database = root / "gip.sqlite"
			with patch("scripts.wienwide_gip.read_manifest",
				return_value=(manifest, aoi)), patch(
				"scripts.wienwide_gip.urls_for_tile",
				return_value=({"achsen": "a", "knoten": "n"}, None)):
				stats = build_index(manifest_path,
					root / "gip_fragmente", database)
			self.assertEqual(stats["achsen"], 1)
			self.assertEqual(stats["knoten"], 2)
			self.assertEqual(stats["duplikate_zusammengefuehrt"][
				"routenvarianten_in_kachel"], 2)
			self.assertEqual(stats["achsen_mit_mehreren_reg_strname"], 1)
			self.assertEqual(stats["achsen_quellvarianten"], 2)
			with sqlite3.connect(database) as db:
				rows = db.execute("""SELECT gip,wfs_id,reg_strname,kachel_vorkommen
					FROM axis_source_variants ORDER BY reg_strname""").fetchall()
				self.assertEqual(rows, [
					("10026184", "STRASSENGRAPHOGD.61196089", "B12", 2),
					("10026184", "STRASSENGRAPHOGD.61196034", "B13a", 2),
				])
				self.assertEqual(db.execute(
					"SELECT COUNT(*) FROM axes").fetchone()[0], 1)
				self.assertEqual(db.execute(
					"SELECT SUM(degree) FROM node_degrees").fetchone()[0], 2)

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
