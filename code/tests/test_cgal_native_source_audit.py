import unittest
from shapely.geometry import LineString,box
from scripts.cgal_native_source_audit import audit_native_shared_sources
from scripts.cgal_shared_boundary_audit import audit_shared_boundaries

A=("P",(0.,0.))
B=("P",(1000.,0.))
C=("P",(2000.,0.))

class NativeSourceAuditTests(unittest.TestCase):
	def test_distinct_native_edges_on_same_shared_boundary(self):
		window=box(0,0,2,1)
		faces=[box(0,0,1,1),box(1,0,2,1)]
		edge=LineString([(1,0),(1,1)])
		source=[(edge,(A,B)),(edge,(A,C))]
		shared=audit_shared_boundaries(faces,[None,B],source)
		native=[(0,(A,B),[("S",(1000.,0.,1000.,1000.))]),
			(1,(A,C),[("S",(1000.,0.,1000.,1000.))])]
		result=audit_native_shared_sources(shared,native,source,window)
		self.assertEqual(result[0]["distinct_native_E_records"],2)
		self.assertEqual(result[0]["distinct_generator_pairs"],2)

	def test_mismatched_native_source_fails_closed(self):
		window=box(0,0,2,1)
		edge=LineString([(1,0),(1,1)])
		with self.assertRaises(ValueError):
			audit_native_shared_sources([],
				[(0,(A,B),[("S",(0.,0.,0.,1000.))])],
				[(edge,(A,B))],window)

if __name__=="__main__":
	unittest.main()
