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

	def test_missing_generator_is_not_guessed(self):
		labels,counts=classify_polygon_generators(
			[box(10,10,11,11)],[(Point(0,0),frozenset({"west"}))])
		self.assertEqual(labels,[None])
		self.assertEqual(counts["missing"],1)

	def test_distinct_sites_inside_same_polygon_are_ambiguous(self):
		sites=[(Point(1,1),frozenset({"a"})),
			(Point(2,2),frozenset({"b"}))]
		labels,counts=classify_polygon_generators([box(0,0,3,3)],sites)
		self.assertEqual(labels,[None])
		self.assertEqual(counts["ambiguous"],1)


if __name__=="__main__":
	unittest.main()
