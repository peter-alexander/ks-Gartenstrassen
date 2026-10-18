import unittest

from shapely.geometry import box

from scripts.street_embedding import (
	make_contact_surfaces, measure_embedding, normal_sector_lengths,
)


class StreetEmbeddingTest(unittest.TestCase):
	def test_green_between_roadway_and_sidewalk(self):
		green = box(0, 0, 3, 3)
		core = {
			21: box(-2, -3, 5, 0),
			23: box(-2, 3, 5, 6),
		}
		info = measure_embedding(green, core)
		self.assertEqual(info["einbettung"], "mehrseitig_verschiedene_klassen")
		self.assertTrue(info["mehrseitiger_kontakt"])
		self.assertTrue(info["gegenueber_verschiedene_klassen"])
		self.assertEqual(info["kontaktklassen"], "21,23")
		self.assertGreater(info["kontakt_21_m"], 2.9)
		self.assertGreater(info["kontakt_23_m"], 2.9)

	def test_tree_pit_enclosed_by_same_sidewalk_class(self):
		green = box(0, 0, 2, 2)
		sidewalk = box(-2, -2, 4, 4).difference(green)
		info = measure_embedding(green, {23: sidewalk})
		self.assertEqual(info["einbettung"], "mehrseitig")
		self.assertTrue(info["mehrseitiger_kontakt"])
		self.assertFalse(info["gegenueber_verschiedene_klassen"])
		self.assertEqual(set(info["kontakt_sektoren"].split(",")), {"O", "N", "W", "S"})

	def test_long_private_garden_touching_only_one_side_is_not_embedded(self):
		garden = box(-100, 0, 100, 30)
		sidewalk = box(-105, -3, 105, 0)
		info = measure_embedding(garden, {23: sidewalk})
		self.assertEqual(info["einbettung"], "einseitig")
		self.assertFalse(info["mehrseitiger_kontakt"])
		self.assertEqual(info["kontakt_sektoren"], "S")
		self.assertGreater(info["kontakt_23_m"], 190)

	def test_two_different_core_classes_on_same_side_are_not_opposite(self):
		green = box(-10, 0, 10, 4)
		core = {21: box(-12, -3, 0, 0), 23: box(0, -3, 12, 0)}
		info = measure_embedding(green, core)
		self.assertEqual(info["einbettung"], "einseitig")
		self.assertFalse(info["gegenueber_verschiedene_klassen"])
		self.assertEqual(info["kontaktklassen"], "21,23")

	def test_point_contact_does_not_count_as_meaningful_side(self):
		green = box(0, 0, 3, 3)
		core = {21: box(3, 3, 8, 8)}
		info = measure_embedding(green, core)
		self.assertEqual(info["einbettung"], "kein_deutlicher_randkontakt")
		self.assertFalse(info["mehrseitiger_kontakt"])

	def test_overlapping_source_geometry_is_qa_case(self):
		green = box(0, 0, 3, 3)
		info = measure_embedding(green, {21: box(1, 1, 4, 4)}, has_core_overlap=True)
		self.assertEqual(info["einbettung"], "ueberlappung_pruefen")

	def test_surfaces_only_include_valid_core_class_codes(self):
		features = [
			(1, 21, "Fahrbahn", box(0, 0, 1, 1)),
			(2, 58, "Grünfläche", box(1, 0, 2, 1)),
			(3, 39, "Sonstige Verkehrsfläche", box(0, 1, 1, 2)),
			(4, 25, "Gehweg, Radweg", box(2, 1, 3, 2)),
		]
		surfaces = make_contact_surfaces(features)
		self.assertEqual(set(surfaces), {21, 25, 39})
		self.assertAlmostEqual(surfaces[25].area, 1)
		self.assertAlmostEqual(surfaces[21].area, 1)
		with self.assertRaisesRegex(ValueError, "Keine Straßenkernklassen"):
			make_contact_surfaces(features[1:2])


if __name__ == "__main__":
	unittest.main()
