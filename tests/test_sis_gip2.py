"""Lokale GIP-2.0-Adaptertests ohne vollständigen österreichischen GIP-Datensatz."""
import sqlite3
import struct
import unittest

from shapely.geometry import LineString, MultiPoint, Point
from shapely.wkb import dumps

from scripts.sis_gip2 import gpkg_geom


def gpkg(geometry, envelope=0):
	# GeoPackage WKB header: GP / version 0 / flags little-endian / EPSG 4326.
	flag = 1 | (envelope << 1)
	extras = b"\x00" * (0, 32, 48, 48, 64)[envelope]
	return b"GP" + bytes((0,flag)) + struct.pack("<i",4326) + extras + dumps(geometry)


class GIP2GeometryTests(unittest.TestCase):
	def test_gpkg_geometry_without_envelope(self):
		g = Point(16.3627,48.1907)
		self.assertTrue(gpkg_geom(gpkg(g)).equals(g))

	def test_gpkg_geometry_with_xy_envelope(self):
		g = LineString([(16.36,48.19),(16.37,48.20)])
		self.assertTrue(gpkg_geom(gpkg(g,1)).equals(g))

	def test_invalid_gpkg_header(self):
		with self.assertRaisesRegex(ValueError,"GeoPackage"):
			gpkg_geom(b"not gpkg")

	def test_convex_hull_ignores_interior_points(self):
		points = [(0,0),(3,0),(3,2),(0,2),(1,1),(2,1)]
		hull = MultiPoint(points).convex_hull
		self.assertEqual(hull.geom_type,"Polygon")
		self.assertAlmostEqual(hull.area,6.)

	def test_degenerate_hull_is_not_polygon(self):
		self.assertEqual(MultiPoint([(0,0),(1,0),(2,0)]).convex_hull.geom_type,
			"LineString")


if __name__=="__main__":
	unittest.main()
