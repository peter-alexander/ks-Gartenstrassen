import unittest

from scripts.cgal_site_audit import inspect_sites


class CgalSiteAuditTests(unittest.TestCase):
	def setUp(self):
		self.owners={
			((0,0),(10,0)):"west",
			((10,0),(20,0)):"east"
		}

	def test_segment_owners_and_ambiguous_joint_point(self):
		report=inspect_sites(["S 0 0 10 0","S 20 0 10 0",
			"P 10 0","P 0 0"],self.owners)
		self.assertEqual(report["segment_sites"],2)
		self.assertEqual(report["unmatched_segments"],0)
		self.assertEqual(report["point_sites"],2)
		self.assertEqual(report["ambiguous_point_sites"],1)

	def test_unknown_generator_is_reported(self):
		report=inspect_sites(["P 99 99","S 12 1 20 0"],self.owners)
		self.assertEqual(report["unmatched_points"],1)
		self.assertEqual(report["unmatched_segments"],1)

	def test_invalid_format_rejected(self):
		with self.assertRaisesRegex(ValueError,"Zeile 1"):
			inspect_sites(["S 0 0 10"],self.owners)


if __name__=="__main__":
	unittest.main()
