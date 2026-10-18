import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shapely.geometry import LineString, Point, box, mapping
from shapely.ops import transform
from pyproj import Transformer

from scripts.assign_gip_section_areas import (
	LONLAT, as_feature, partition, prepare_graph, run,
)


def axis(gid, coordinates, start, end, *, fow=3, name="Testgasse"):
	return {"id": str(gid), "name": name, "fow": fow,
		"geometry": LineString(coordinates),
		"start": str(start), "end": str(end)}


def node(gid, point):
	return {"id": str(gid), "name": f"Knoten {gid}",
		"geometry": Point(point)}


def model():
	street = box(0, 0, 100, 60)
	axes = [
		axis(1, [(0, 30), (50, 30)], 100, 101),
		axis(2, [(50, 30), (100, 30)], 101, 102),
		axis(3, [(50, 0), (50, 30)], 103, 101),
		axis(4, [(50, 30), (50, 60)], 101, 104),
	]
	nodes = [
		node(100, (0, 30)), node(101, (50, 30)),
		node(102, (100, 30)), node(103, (50, 0)),
		node(104, (50, 60)),
	]
	return street, axes, nodes


class AreaPartitionTests(unittest.TestCase):
	def test_disjoint_complete_partition_and_junction_buffer(self):
		street, axes, nodes = model()
		sections, unresolved, stats = partition(street, axes, nodes,
			spacing_m=4, node_radius_m=7, max_distance_m=32)
		self.assertEqual(stats["anzahl_zugeordnete_abschnitte"], 4)
		self.assertEqual(stats["anzahl_kreuzungsknoten"], 1)
		self.assertGreater(stats["ungeklaert_nach_typ_m2"]["knotenbereich"], 0)
		self.assertLess(abs(stats["bilanzdifferenz_m2"]), 1e-5)
		self.assertLess(stats["ueberlappung_m2"], 1e-5)
		self.assertLess(stats["fehlend_m2"], 1e-5)
		self.assertLess(stats["ausserhalb_m2"], 1e-5)
		self.assertAlmostEqual(stats["gesamt_m2"], street.area, places=5)
		self.assertTrue(all(geom.is_valid for _, geom in sections))
		self.assertTrue(all(geom.is_valid for _, geom in unresolved))
		self.assertEqual(len({a["id"] for a, _ in sections}), 4)

	def test_special_fow_and_far_areas_are_not_assigned(self):
		street, axes, nodes = model()
		axes.append(axis(5, [(0, 48), (100, 48)], 105, 106,
			fow=15, name="Promenade"))
		nodes += [node(105, (0, 48)), node(106, (100, 48))]
		sections, unresolved, stats = partition(street, axes, nodes,
			spacing_m=5, node_radius_m=5, max_distance_m=10)
		kinds = {key: geom.area for key, geom in unresolved}
		self.assertGreater(kinds["sonderachse"], 0)
		self.assertGreater(kinds["nicht_zugeordnet"], 0)
		self.assertLess(stats["ueberlappung_m2"], 1e-5)
		self.assertAlmostEqual(stats["gesamt_m2"], street.area, places=5)
		self.assertTrue(all(axis["fow"] == 3 for axis, _ in sections))

	def test_rejects_unsafe_parameters_and_duplicate_sites(self):
		street, axes, nodes = model()
		for values in (
			{"spacing_m": 0.1}, {"node_radius_m": 0},
			{"max_distance_m": 1000}, {"spacing_m": float("nan")},
		):
			with self.subTest(values=values), self.assertRaises(ValueError):
				partition(street, axes, nodes, **values)
		with self.assertRaisesRegex(ValueError, "Deckungsgleiche"):
			partition(street, [axes[0], {**axes[0], "id": "duplicate"}],
				nodes)

	def test_empty_or_invalid_street_is_rejected(self):
		_, axes, nodes = model()
		with self.assertRaisesRegex(ValueError, "Straßenraum"):
			partition(box(0, 0, 0, 0), axes, nodes)
		with self.assertRaisesRegex(ValueError, "Straßenraum"):
			partition(LineString([(0, 0), (1, 1)]), axes, nodes)

	def test_end_to_end_writes_both_layers_and_never_overwrites(self):
		# Verankere Test geometrisch in der Wiener EPSG:31256-Region.
		x0, y0 = 2200, 343000
		street, axes, nodes = model()
		def moved(g):
			return transform(lambda x, y: (x + x0, y + y0), g)
		street = moved(street)
		for entry in axes + nodes:
			entry["geometry"] = moved(entry["geometry"])
		with tempfile.TemporaryDirectory() as temp:
			root = Path(temp)
			gip = root / "gip"
			gip.mkdir()
			bbox = [16.361012, 48.221226, 16.366948, 48.224902]
			(gip / "gip_probe_bericht.json").write_text(json.dumps({
				"schema_version": 1, "fmzk_bbox_lon_lat": bbox,
				"datensaetze": {"achsen": {"anzahl": len(axes)},
					"knoten": {"anzahl": len(nodes)}},
			}))
			af = [
				{"type": "Feature", "id": f"edge.{a['id']}",
					"geometry": mapping(transform(LONLAT, a["geometry"])),
					"properties": {"gip_objectid": a["id"],
						"name": a["name"], "fow": a["fow"],
						"node_from": a["start"], "node_to": a["end"]}}
				for a in axes]
			nf = [
				{"type": "Feature", "id": f"node.{n['id']}",
					"geometry": mapping(transform(LONLAT, n["geometry"])),
					"properties": {"gip_objectid": n["id"],
						"name": n["name"]}}
				for n in nodes]
			(gip / "abschnitte_achsen.geojson").write_text(json.dumps({
				"type": "FeatureCollection", "features": af}))
			(gip / "abschnitte_knoten.geojson").write_text(json.dumps({
				"type": "FeatureCollection", "features": nf}))
			out = root / "out"
			with patch("scripts.assign_gip_section_areas.load_polygons",
				return_value=([], {"bbox_lon_lat": bbox}, street, [])), patch(
				"scripts.assign_gip_section_areas.load_street_mask",
				return_value=(street, {"masken_sha256": "valid-hash"})), patch(
				"scripts.assign_gip_section_areas.audit",
				return_value={"status": "topologie_konsistent"}):
				report = run(street=root/"street.geojson",
					fmzk=root/"fmzk.gpkg", gip=gip, output=out,
					node_radius_m=5, max_distance_m=32)
				with self.assertRaisesRegex(FileExistsError, "existiert"):
					run(street=root/"street.geojson",
						fmzk=root/"fmzk.gpkg", gip=gip, output=out)
			self.assertAlmostEqual(report["bilanz"]["strassenraum_m2"],
				6000, places=5)
			self.assertLess(report["bilanz"]["fehlend_m2"], 1e-5)
			self.assertEqual(report["quelle"]["strassenraum_sha256"], "valid-hash")
			for filename in ("abschnitte_flaechen.geojson",
				"abschnitte_ungeklaert.geojson", "abschnitte_bericht.json"):
				self.assertTrue((out / filename).is_file())
			fc = json.loads((out / "abschnitte_flaechen.geojson").read_text())
			self.assertEqual(len(fc["features"]), 4)
			self.assertEqual(fc["features"][0]["geometry"]["type"], "Polygon")


if __name__ == "__main__":
	unittest.main()
