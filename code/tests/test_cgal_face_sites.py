"""Synthetic checks for explicit CGAL generator / face association."""
import unittest

from shapely.geometry import Point, box

from scripts.cgal_face_sites import (
	_read_sites, classify_polygon_generators)


class FaceSiteTests(unittest.TestCase):
	def test_unique_segment_site_assigns_face(self):
		owners={((0,0),(10000,0)):"west",((20000,0),(30000,0)):"east"}
		sites=_read_sites(["S 0 0 10000 0","S 20000 0 30000 0"],
			owners,(0,0),1000)
		labels,counts=classify_polygon_generators(
			[box(-1,-1,15,5),box(16,-1,35,5)],sites)
		self.assertEqual(labels,["west","east"])
		self.assertEqual(counts["unambiguous"],2)

	def test_shared_endpoint_not_attributed_arbitrarily(self):
		owners={((0,0),(10000,0)):"west",((10000,0),(20000,0)):"east"}
		sites=_read_sites(["P 10000 0"],owners,(0,0),1000)
		labels,counts=classify_polygon_generators([box(9,-1,11,1)],sites)
		self.assertEqual(labels,[None])
		self.assertEqual(counts["ambiguous"],1)

	def test_segment_intersection_detected_without_midpoint_containment(self):
		# A long segment crosses the face, but its midpoint is elsewhere.
		owners={((0,0),(20000,0)):"axis"}
		sites=_read_sites(["S 0 0 20000 0"],owners,(0,0),1000)
		labels,stats=classify_polygon_generators(
			[box(0,-1,4,1)],sites)
		self.assertEqual(labels,[None])
		self.assertEqual(stats["missing"],1)
		sample=stats["unresolved_examples"][0]
		self.assertEqual(sample["intersecting_segment_sites"],1)
		self.assertEqual(sample["intersecting_segment_owner_count"],1)

	def test_window_boundary_vs_interior_missing(self):
		sites=[(Point(1,1),frozenset({"source"}))]
		polygons=[box(0,2,4,4),box(5,5,7,7)]
		labels,stats=classify_polygon_generators(polygons,sites,
			window_bounds=(0,0,10,10))
		self.assertEqual(labels,[None,None])
		self.assertEqual(stats["missing_boundary_faces"],1)
		self.assertEqual(stats["missing_interior_faces"],1)
		self.assertEqual(stats["ambiguous_boundary_faces"],0)
		self.assertEqual(len(stats["unresolved_examples"]),1)
		self.assertEqual(len(stats["unresolved_interior_examples"]),1)
		self.assertTrue(stats["unresolved_examples"][0]["touches_window_boundary"])
		self.assertFalse(stats["unresolved_interior_examples"][0]["touches_window_boundary"])

	def test_area_distribution_exposes_large_missing_and_sliver_faces(self):
		sites=[(Point(1,1),frozenset({"known"}))]
		polygons=[box(0,0,2,2),box(20,20,21,21),
			box(30,30,130,130),box(5,5,5.001,5.001)]
		labels,stats=classify_polygon_generators(polygons,sites)
		self.assertEqual(labels,["known",None,None,None])
		missing=stats["area_distribution"]["missing"]
		self.assertEqual(missing["count"],3)
		self.assertAlmostEqual(missing["area_m2"],10001.000001)
		self.assertEqual([v["count"] for v in missing["by_size"]],
			[1,0,1,0,1])
		self.assertEqual(stats["area_distribution"]["unambiguous"]["count"],1)

	def test_unmapped_site_is_kept_ownerless(self):
		owners={((0,0),(10000,0)):"street"}
		sites=_read_sites(["S 0 0 10000 0",
			"S 100000 100000 200000 100000",
			"P 150000 100000"],owners,(0,0),1000)
		self.assertEqual(sites[0][1],frozenset({"street"}))
		self.assertEqual(sites[1][1],frozenset())
		self.assertEqual(sites[2][1],frozenset())
		labels,stats=classify_polygon_generators(
			[box(90,95,210,105)],sites)
		self.assertEqual(labels,[None])
		self.assertEqual(stats["ownerless_generator_faces"],1)

	def test_ownerless_generator_prevents_false_unique_owner(self):
		sites=[(Point(1,1),frozenset({"street"})),
			(Point(2,2),frozenset())]
		labels,stats=classify_polygon_generators([box(0,0,3,3)],sites)
		self.assertEqual(labels,[None])
		self.assertEqual(stats["ownerless_generator_faces"],1)

	def test_missing_generator_is_not_guessed(self):
		labels,counts=classify_polygon_generators(
			[box(10,10,11,11)],[(Point(0,0),frozenset({"west"}))])
		self.assertEqual(labels,[None])
		self.assertEqual(counts["missing"],1)

	def test_unresolved_samples_identify_missing_and_ambiguous(self):
		sites=[(Point(1,1),frozenset({"west"})),
			(Point(2,2),frozenset({"east"}))]
		faces=[box(0,0,3,3),box(10,10,12,12)]
		labels,stats=classify_polygon_generators(faces,sites)
		self.assertEqual(labels,[None,None])
		examples=stats["unresolved_examples"]
		self.assertEqual({x["category"] for x in examples},
			{"ambiguous","missing"})
		self.assertEqual([x["face_index"] for x in examples],[0,1])
		self.assertEqual(examples[0]["site_count_in_face"],2)
		self.assertEqual(examples[1]["site_count_in_face"],0)
		self.assertGreater(examples[1]["nearest_site_distance_m"],0)

	def test_distinct_sites_inside_same_polygon_are_ambiguous(self):
		sites=[(Point(1,1),frozenset({"a"})),
			(Point(2,2),frozenset({"b"}))]
		labels,counts=classify_polygon_generators([box(0,0,3,3)],sites)
		self.assertEqual(labels,[None])
		self.assertEqual(counts["ambiguous"],1)


if __name__=="__main__":
	unittest.main()
