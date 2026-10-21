import unittest
from shapely.geometry import box
from scripts.cgal_unresolved_native_source_census import audit_unresolved_native_sources

WINDOW=box(0,0,10,10)
FACE=box(1,1,9,9)
P=("P",(1000.,1000.))
S=("S",(1000.,1000.,9000.,1000.))
EDGES=[(0,(P,S),[("S",[1000,1000,9000,1000])]),
	(1,(P,S),[("S",[1000,1000,9000,1000])])]

class UnresolvedNativeSourceCensusTests(unittest.TestCase):
	def test_duplicate_native_sources_are_not_owners(self):
		row=audit_unresolved_native_sources([FACE],[None],EDGES,WINDOW)[0]
		self.assertEqual(row["distinct_native_edges"],2)
		self.assertEqual(row["distinct_site_pairs"],1)
		self.assertEqual(len(row["boundary_source_records"]),2)
		self.assertFalse(row["ownership_proven"])

	def test_proven_face_not_in_report(self):
		self.assertEqual(audit_unresolved_native_sources([FACE],[P],EDGES,WINDOW),[])

	def test_no_native_boundary_source_does_not_promote(self):
		row=audit_unresolved_native_sources([FACE],[None],[],WINDOW)[0]
		self.assertEqual(row["boundary_source_records"],[])
		self.assertFalse(row["ownership_proven"])

	def test_mismatched_labels_rejected(self):
		with self.assertRaises(ValueError):
			audit_unresolved_native_sources([FACE],[],EDGES,WINDOW)

	def test_invalid_native_primitive_rejected(self):
		with self.assertRaises(ValueError):
			audit_unresolved_native_sources([FACE],[None],
				[(0,(P,S),[("X",[0,0,1,1])])],WINDOW)

if __name__=="__main__":
	unittest.main()
