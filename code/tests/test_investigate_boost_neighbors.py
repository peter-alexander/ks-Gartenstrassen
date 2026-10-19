"""Spatial comparisons for Boost-site performance investigation."""
import unittest

from scripts.investigate_boost_neighbors import _nearby


class NeighborInvestigationTests(unittest.TestCase):
	def test_nearby_uses_distance_between_segments_not_midpoints(self):
		target=((0,0),(100000,0))
		close=((99000,500),(99000,10000))
		far=((0,20000),(100000,20000))
		segments=[target,close,far]
		result=_nearby(segments,target,1)
		self.assertEqual([item[0] for item in result],[target,close])
		self.assertAlmostEqual(result[1][1],0.5)

	def test_radius_rejects_negative_values(self):
		with self.assertRaises(ValueError):
			_nearby([((0,0),(1000,0))],((0,0),(1000,0)),-1)


if __name__=="__main__":
	unittest.main()
