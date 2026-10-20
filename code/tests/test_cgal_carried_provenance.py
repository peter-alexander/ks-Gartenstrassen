import unittest

from shapely.geometry import LineString,box

from scripts.cgal_carried_provenance import carried_provenance


A=("P",(0.,0.))
B=("P",(1.,0.))
C=("P",(2.,0.))


class CarriedProvenanceTests(unittest.TestCase):
	def test_label_survives_noding_crossing(self):
		window=box(0,0,2,2)
		sources=[LineString([(0,1),(2,1)]),LineString([(1,0),(1,2)])]
		_,edges=carried_provenance(window,sources,
			[frozenset((A,B)),frozenset((B,C))])
		vertical=[labels for line,labels in edges
			if all(abs(pt[0]-1)<1e-8 for pt in line.coords)
			and abs(line.centroid.y-1)>.25]
		self.assertEqual(len(vertical),2)
		self.assertTrue(all(frozenset((B,C)) in labels for labels in vertical))

	def test_many_unrelated_nodes_do_not_change_provenance(self):
		window=box(0,0,100,100)
		sources=[LineString([(10,10),(90,10)]),
			LineString([(50,0),(50,100)])]
		sources.extend(LineString([(x,50),(x,55)])
			for x in range(2,99,5))
		pairs=[frozenset((A,B)),frozenset((B,C))]
		pairs.extend([frozenset((A,C))]*(len(sources)-2))
		_,edges=carried_provenance(window,sources,pairs)
		at_horizontal=[labels for edge,labels in edges
			if edge.length>0 and abs(edge.centroid.y-10)<1e-8
			and 10<edge.centroid.x<90]
		self.assertGreaterEqual(len(at_horizontal),2)
		self.assertTrue(all(frozenset((A,B)) in labels
			for labels in at_horizontal))

	def test_unlabelled_window_edges_remain_unlabelled(self):
		_,edges=carried_provenance(box(0,0,2,2),
			[LineString([(1,0),(1,2)])],[frozenset((A,B))])
		self.assertTrue(any(not labels for line,labels in edges))

	def test_overlaid_conflicting_source_pairs_remain_ambiguous(self):
		line=LineString([(1,0),(1,2)])
		_,edges=carried_provenance(box(0,0,2,2),[line,line],
			[frozenset((A,B)),frozenset((B,C))])
		self.assertTrue(any(len(labels)==2 for _,labels in edges))


if __name__=="__main__":
	unittest.main()
