"""Checks finite true-segment Voronoi cell reconstruction."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from shapely.geometry import LineString, box
from scripts.build_segment_voronoi_geojson import _cell_polygon, _bounded_diagram


class SegmentVoronoiPolygonTests(unittest.TestCase):
	def test_closed_linear_cell(self):
		vertices=[SimpleNamespace(X=x,Y=y) for x,y in
			((0,0),(10,0),(10,10),(0,10))]
		edges=[SimpleNamespace(start=i,end=(i+1)%4,is_linear=True)
			for i in range(4)]
		cell=SimpleNamespace(is_open=False,site=0,edges=[0,1,2,3])
		polygon=_cell_polygon(None,cell,edges,vertices,(100,200))
		self.assertTrue(polygon.is_valid)
		self.assertAlmostEqual(polygon.area,100)
		self.assertEqual(polygon.bounds,(100,200,110,210))

	def test_infinite_cell_rejected(self):
		cell=SimpleNamespace(is_open=True,site=5,edges=[])
		with self.assertRaisesRegex(ValueError,"Nicht geschlossene"):
			_cell_polygon(None,cell,[],[],(0,0))

	def test_unconnected_halfedges_rejected(self):
		vertices=[SimpleNamespace(X=x,Y=y) for x,y in
			((0,0),(10,0),(10,10),(0,10))]
		edges=[SimpleNamespace(start=0,end=1,is_linear=True),
			SimpleNamespace(start=2,end=3,is_linear=True)]
		cell=SimpleNamespace(is_open=False,site=0,edges=[0,1])
		with self.assertRaisesRegex(ValueError,"Unverbundene"):
			_cell_polygon(None,cell,edges,vertices,(0,0))

	def test_true_boost_segment_diagram_has_finite_real_cells(self):
		try:
			import pyvoronoi
		except ImportError:
			self.skipTest("pyvoronoi nicht installiert")
		pv,owners,origin=_bounded_diagram([
			("a",LineString([(0,0),(100,0)])),
			("b",LineString([(0,20),(100,20)]))],box(-5,-5,105,25))
		cells=pv.GetCells()
		edges=pv.GetEdges()
		vertices=pv.GetVertices()
		geometries=[]
		for cell in cells:
			if owners[cell.site] is None:
				continue
			geometries.append(_cell_polygon(pv,cell,edges,vertices,origin))
		self.assertTrue(geometries)
		self.assertTrue(all(p.is_valid for p in geometries))


if __name__=="__main__":
	unittest.main()
