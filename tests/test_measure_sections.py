"""Offline-Regressionen für Modul 6: abschnittsweise reale Schnittlogik."""
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shapely.geometry import box, mapping
from shapely.ops import transform
from scripts.measure_sections import (
	TO_LONLAT, compute_rows, read_partition, run, sha256,
)


def feature(fid, geom, *, group, label="", area=None):
	prop = {"flaeche_m2": geom.area if area is None else area}
	if group == "abschnitt":
		prop |= {"gip_objectid": fid.replace("gip:", ""),
			"name": label, "status": "experimentell_achsennaehe"}
	else:
		prop |= {"status": fid.replace("ungeklaert:", "")}
	return {"type": "Feature", "id": fid, "properties": prop,
		"geometry": mapping(transform(TO_LONLAT, geom))}


def fc(features):
	return {"type": "FeatureCollection", "features": features}


class SectionMetricsTests(unittest.TestCase):
	def setUp(self):
		self.dir = tempfile.TemporaryDirectory()
		self.addCleanup(self.dir.cleanup)
		self.root = Path(self.dir.name)
		# Realistische metrische Koordinaten nahe Wien.
		from scripts.measure_sections import TO_METRIC
		x, y = TO_METRIC(16.363, 48.223)
		self.street = box(x, y, x + 100, y + 40)
		self.left = box(x, y, x + 45, y + 40)
		self.right = box(x + 55, y, x + 100, y + 40)
		self.unresolved = box(x + 45, y, x + 55, y + 40)
		self.greening = box(x + 20, y + 10, x + 65, y + 30)  # 900 m²
		self.a = box(x + 30, y, x + 75, y + 30)
		self.b = box(x + 30, y, x + 80, y + 30)
		self.c = box(x + 5, y + 15, x + 90, y + 40)
		self.v0 = self.root / "v0"
		self.v0.mkdir()
		self.mask = self.root / "strassenraum.geojson"
		self.mask.write_text(json.dumps(fc([feature(
			"street", self.street, group="abschnitt")])), encoding="utf-8")
		self.masksha = sha256(self.mask)
		self.gpkg = self.root / "fmzk_test.gpkg"
		self.gpkg.write_bytes(b"synthetisches, lokal gemocktes FMZK")
		self.crownpaths = [self.root / f"canopy_{i}.geojson"
			for i in range(3)]
		for p in self.crownpaths:
			p.write_text("{}")
		self._write_v0()

	def _write_v0(self, *, parts=None, unresolved=None, source_hash=None,
		radius=7):
		if parts is None:
			parts = [
				feature("gip:1001", self.left, group="abschnitt", label="A-Gasse"),
				feature("gip:1002", self.right, group="abschnitt", label="B-Gasse"),
			]
		if unresolved is None:
			unresolved = [feature("ungeklaert:knotenbereich",
				self.unresolved, group="ungeklaert")]
		(self.v0 / "abschnitte_flaechen.geojson").write_text(
			json.dumps(fc(parts)), encoding="utf-8")
		(self.v0 / "abschnitte_ungeklaert.geojson").write_text(
			json.dumps(fc(unresolved)), encoding="utf-8")
		report = {"schema_version": 1,
			"status": "EXPERIMENTELL – NICHT VALIDIERTE STRASSENABSCHNITTE",
			"parameter": {"knotenradius_m": radius,
				"sample_spacing_m": 5, "max_axis_distance_m": 25,
				"gip_standard_fow": 3},
			"quelle": {"strassenraum_sha256":
				source_hash if source_hash is not None else self.masksha},
			"bilanz": {"strassenraum_m2": self.street.area,
				"zugeordnet_m2": self.left.area + self.right.area,
				"ungeklaert_m2": self.unresolved.area,
				"anzahl_zugeordnete_abschnitte": len(parts)}}
		(self.v0 / "abschnitte_bericht.json").write_text(
			json.dumps(report), encoding="utf-8")

	def test_partition_validates_complete_area_and_source(self):
		parts, stats, report = read_partition(self.v0, self.street,
			street_sha256=self.masksha)
		self.assertEqual(stats["abschnitte"], 2)
		self.assertEqual(stats["ungeklaerte_klassen"], 1)
		self.assertAlmostEqual(stats["strassenraum_m2"], 4000)
		self.assertLess(stats["geometrische_ueberlappung_m2"], .001)
		self.assertEqual([p["id"] for p in parts],
			["gip:1001", "gip:1002", "ungeklaert:knotenbereich"])

	def test_section_and_rest_metrics_reconcile_all_totals(self):
		parts, _stats, _ = read_partition(self.v0, self.street,
			street_sha256=self.masksha)
		rows, totals = compute_rows(parts, self.street, {
			"bodenbegruenung": self.greening,
			"kronen_a": self.a, "kronen_b": self.b, "kronen_c": self.c,
		})
		self.assertEqual(len(rows), 3)
		self.assertIsNone(rows[0]["vegetation_d_m2"])
		self.assertEqual(rows[0]["id"], "gip:1001")
		self.assertEqual(rows[2]["gruppe"], "ungeklaert")
		self.assertAlmostEqual(totals["bodenbegruenung"]["gesamt_m2"], 900)
		self.assertAlmostEqual(totals["kronen_a"]["gesamt_m2"], 1350)
		self.assertAlmostEqual(totals["kronen_b"]["gesamt_m2"], 1500)
		self.assertAlmostEqual(totals["kronen_c"]["gesamt_m2"], 2125)
		for name, result in totals.items():
			if result is not None:
				self.assertLessEqual(abs(result["abschnitte_m2"] +
					result["ungeklaert_m2"] - result["gesamt_m2"]), .5)
				self.assertLessEqual(
					abs(result["bilanzdifferenz_m2"]), .5)
		self.assertGreater(totals["bodenbegruenung"]["ungeklaert_m2"], 0)
		self.assertGreater(totals["kronen_a"]["ungeklaert_m2"], 0)

	def test_partition_rejects_changed_mask_radius_overlaps_and_gaps(self):
		self._write_v0(source_hash="other")
		with self.assertRaisesRegex(ValueError, "SHA-256"):
			read_partition(self.v0, self.street, street_sha256=self.masksha)
		self._write_v0(radius=9)
		with self.assertRaisesRegex(ValueError, "Parameter"):
			read_partition(self.v0, self.street, street_sha256=self.masksha)
		self._write_v0(parts=[
			feature("gip:1001", self.left, group="abschnitt"),
			feature("gip:1002", self.left, group="abschnitt"),
		])
		with self.assertRaises(ValueError):
			read_partition(self.v0, self.street, street_sha256=self.masksha)
		# Eine Lücke darf auch bei passend gefälschten Metadaten
		# keinesfalls als gültige Straßenraum-Partition gelten.
		self._write_v0(parts=[
			feature("gip:1001", self.left, group="abschnitt"),
		])
		with self.assertRaises(ValueError):
			read_partition(self.v0, self.street, street_sha256=self.masksha)

	def test_duplicate_ids_and_wrong_attributes_rejected(self):
		self._write_v0(parts=[
			feature("gip:1001", self.left, group="abschnitt"),
			feature("gip:1001", self.right, group="abschnitt"),
		])
		with self.assertRaisesRegex(ValueError, "doppelte"):
			read_partition(self.v0, self.street, street_sha256=self.masksha)
		self._write_v0(parts=[
			feature("gip:1001", self.left, group="abschnitt"),
			feature("gip:1002", self.right, group="abschnitt", area=150),
		])
		with self.assertRaisesRegex(ValueError, "Quellenfläche"):
			read_partition(self.v0, self.street, street_sha256=self.masksha)

	def test_optional_d_is_separate_not_added_to_canopies(self):
		parts, _, _ = read_partition(self.v0, self.street,
			street_sha256=self.masksha)
		_, totals = compute_rows(parts, self.street, {
			"bodenbegruenung": self.greening,
			"kronen_a": self.a, "kronen_b": self.b, "kronen_c": self.c,
			"vegetation_d": self.greening,
		})
		self.assertEqual(totals["vegetation_d"]["gesamt_m2"], 900)
		self.assertEqual(totals["kronen_c"]["gesamt_m2"], 2125)

	def test_full_offline_workflow_generates_geojson_csv_json_and_no_overwrite(self):
		source = [
			(1, 58, "Grün", self.greening),
			(2, 21, "Fahrbahn", self.street.difference(self.greening)),
		]
		canopies = {
			str(self.crownpaths[0]): self.a,
			str(self.crownpaths[1]): self.b,
			str(self.crownpaths[2]): self.c,
		}
		def read_canopy(path):
			return canopies[str(path)], {"sha256": sha256(path),
				"quell_features": 1}
		output = self.root / "modul6"
		with patch("scripts.measure_sections.load_polygons", return_value=(
			source, {"bbox_lon_lat": [16.36, 48.22, 16.37, 48.23]},
			self.street, [],
		)), patch("scripts.measure_sections.load_street_mask",
			return_value=(self.street, {"masken_sha256": self.masksha})
		), patch("scripts.measure_sections.read_crown_polygons",
			side_effect=read_canopy):
			report = run(sections=self.v0, fmzk=self.gpkg,
				street=self.mask, canopy_a=self.crownpaths[0],
				canopy_b=self.crownpaths[1], canopy_c=self.crownpaths[2],
				output=output)
			with self.assertRaises(FileExistsError):
				run(sections=self.v0, fmzk=self.gpkg,
					street=self.mask, canopy_a=self.crownpaths[0],
					canopy_b=self.crownpaths[1],
					canopy_c=self.crownpaths[2], output=output)
		self.assertEqual(len(report["abschnitte"]), 2)
		self.assertEqual(len(report["ungeklaerte_flaechen"]), 1)
		self.assertEqual(report["v0_parameter"]["knotenradius_m"], 7)
		self.assertAlmostEqual(
			report["gesamtkennzahlen"]["bodenbegruenung"]["gesamt_m2"], 900)
		with (output / "abschnitte_kennzahlen.csv").open(
			encoding="utf-8-sig", newline="") as handle:
			rows = list(csv.DictReader(handle, delimiter=";"))
		self.assertEqual(len(rows), 3)
		self.assertEqual(rows[-1]["gruppe"], "ungeklaert")
		self.assertEqual(rows[0]["name"], "A-Gasse")
		self.assertEqual(rows[0]["vegetation_d_m2"], "")
		geo = json.loads(
			(output / "abschnitte_kennzahlen.geojson").read_text(encoding="utf-8"))
		self.assertEqual(len(geo["features"]), 2)
		self.assertIn("kronen_c_pct", geo["features"][0]["properties"])
		unknown = json.loads(
			(output / "ungeklaerte_kennzahlen.geojson").read_text(
				encoding="utf-8"))
		self.assertEqual(len(unknown["features"]), 1)
		self.assertTrue((output / "abschnitte_kennzahlen_bericht.json").is_file())


if __name__ == "__main__":
	unittest.main()
