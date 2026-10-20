import unittest

from shapely.geometry import box

from scripts.cgal_unresolved_site_audit import inspect_unresolved_faces


class UnresolvedSiteAuditTests(unittest.TestCase):
	def test_multiple_strictly_contained_native_sites_are_reported(self):
		edges=[
			(0,(("P",(2000.,2000.)),("P",(8000.,8000.))),[]),
			(1,(("P",(0.,0.)),("S",(0.,5000.,10000.,5000.))),[])]
		found=inspect_unresolved_faces([box(0,0,10,10)],[None],edges)
		self.assertEqual(len(found),1)
		self.assertEqual(found[0]["strictly_contained_sites"],3)
		self.assertEqual(found[0]["boundary_intersecting_sites"],1)
		self.assertTrue(found[0]["multiple_contained_sites"])

	def test_boundary_point_is_not_counted_as_contained(self):
		edges=[(0,(("P",(0.,0.)),("P",(5000.,5000.))),[])]
		found=inspect_unresolved_faces([box(0,0,10,10)],[None],edges)
		self.assertEqual(found[0]["strictly_contained_sites"],1)
		self.assertEqual(found[0]["boundary_intersecting_sites"],1)

	def test_known_face_is_excluded(self):
		site=("P",(5000.,5000.))
		edges=[(0,(site,("P",(0.,0.))),[])]
		self.assertEqual(inspect_unresolved_faces([box(0,0,10,10)],
			[site],edges),[])


if __name__=="__main__":
	unittest.main()
