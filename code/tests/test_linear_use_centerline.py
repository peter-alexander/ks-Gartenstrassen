"""Synthetic tests for geometric mean axes of already-grouped LINEAR_USE lines."""
import unittest

from shapely.geometry import LineString

from scripts.linear_use_centerline import build_edge_axes, build_mean_axis


class MeanAxisTests(unittest.TestCase):
	def assertCoordsAlmostEqual(self,left,right,places=7):
		self.assertEqual(len(left),len(right))
		for a,b in zip(left,right):
			self.assertAlmostEqual(a[0],b[0],places=places)
			self.assertAlmostEqual(a[1],b[1],places=places)

	def test_single_line_is_returned_exactly(self):
		line=LineString([(0,0),(4,1),(10,1)])
		axis,audit=build_mean_axis([line])
		self.assertTrue(axis.equals_exact(line,0))
		self.assertEqual(audit.method,"single")
		self.assertEqual(audit.input_lines,1)
		self.assertEqual(audit.reversed_lines,0)
		self.assertEqual(audit.length_ratio_min_max,1)
		self.assertEqual(audit.max_correspondence_spread_m,0)

	def test_two_parallel_lines_create_exact_middle(self):
		a=LineString([(0,0),(100,0)])
		b=LineString([(0,10),(100,10)])
		axis,audit=build_mean_axis([a,b],sample_spacing_m=25)
		self.assertCoordsAlmostEqual(list(axis.coords),[
			(0,5),(25,5),(50,5),(75,5),(100,5),
		])
		self.assertEqual(audit.method,"mean_axis")
		self.assertEqual(audit.input_lines,2)
		self.assertEqual(audit.reversed_lines,0)
		self.assertAlmostEqual(audit.max_correspondence_spread_m,10)

	def test_contiguous_split_segments_are_merged_not_averaged(self):
		a=LineString([(0,0),(40,0)])
		b=LineString([(40,0),(100,0)])
		axis,audit=build_mean_axis([a,b],sample_spacing_m=5)
		self.assertTrue(axis.equals(LineString([(0,0),(40,0),(100,0)])))
		self.assertEqual(audit.method,"line_merge")
		self.assertEqual(audit.input_lines,2)
		self.assertAlmostEqual(axis.length,100)
		self.assertEqual(audit.max_correspondence_spread_m,0)

	def test_reversed_contiguous_segments_are_merged(self):
		a=LineString([(40,0),(0,0)])
		b=LineString([(100,0),(40,0)])
		axis,audit=build_mean_axis([a,b])
		self.assertTrue(axis.equals(LineString([(0,0),(40,0),(100,0)])))
		self.assertEqual(audit.method,"line_merge")

	def test_opposite_digitization_does_not_change_middle(self):
		a=LineString([(0,0),(100,0)])
		b=LineString([(100,10),(0,10)])
		axis,audit=build_mean_axis([a,b],sample_spacing_m=50)
		self.assertCoordsAlmostEqual(list(axis.coords),[
			(0,5),(50,5),(100,5),
		])
		self.assertEqual(audit.reversed_lines,1)

	def test_three_lines_use_arithmetic_geometric_middle(self):
		a=LineString([(0,0),(90,0)])
		b=LineString([(0,6),(90,6)])
		c=LineString([(0,15),(90,15)])
		axis,audit=build_mean_axis([a,b,c],sample_spacing_m=30)
		self.assertCoordsAlmostEqual(list(axis.coords),[
			(0,7),(30,7),(60,7),(90,7),
		])
		self.assertEqual(audit.input_lines,3)
		self.assertAlmostEqual(audit.max_correspondence_spread_m,15)
		self.assertAlmostEqual(audit.length_ratio_min_max,1)

	def test_curved_parallel_lines_keep_curved_mean(self):
		a=LineString([(0,0),(10,0),(20,10)])
		b=LineString([(0,4),(10,4),(20,14)])
		axis,audit=build_mean_axis([a,b],sample_spacing_m=100)
		# With only endpoints sampled, both corresponding endpoint means are exact.
		self.assertCoordsAlmostEqual(list(axis.coords),[(0,2),(20,12)])
		self.assertTrue(axis.is_simple)
		self.assertAlmostEqual(audit.max_correspondence_spread_m,4)

	def test_curved_lines_are_sampled_along_normalized_arclength(self):
		a=LineString([(0,0),(10,0),(20,10)])
		b=LineString([(0,4),(10,4),(20,14)])
		axis,_audit=build_mean_axis([a,b],sample_spacing_m=5)
		self.assertGreater(len(axis.coords),2)
		# Every corresponding point differs by exactly four metres vertically,
		# therefore every mean point lies two metres above line a's sample.
		count=len(axis.coords)
		for i,(x,y) in enumerate(axis.coords):
			fraction=i/(count-1)
			p=a.interpolate(fraction,normalized=True)
			self.assertAlmostEqual(x,p.x,places=7)
			self.assertAlmostEqual(y,p.y+2,places=7)

	def test_different_lengths_use_same_normalized_fraction(self):
		a=LineString([(0,0),(100,0)])
		b=LineString([(10,10),(90,10)])
		axis,audit=build_mean_axis([a,b],sample_spacing_m=50)
		self.assertCoordsAlmostEqual(list(axis.coords),[
			(5,5),(50,5),(95,5),
		])
		self.assertAlmostEqual(audit.length_ratio_min_max,.8)
		self.assertGreater(audit.max_correspondence_spread_m,10)

	def test_input_order_only_changes_possible_direction_not_locus(self):
		a=LineString([(0,0),(100,0)])
		b=LineString([(100,10),(0,10)])
		c=LineString([(0,20),(100,20)])
		first,_=build_mean_axis([a,b,c],sample_spacing_m=10)
		second,_=build_mean_axis([c,b,a],sample_spacing_m=10)
		self.assertTrue(first.equals_exact(second,1e-9)
			or first.equals_exact(LineString(list(second.coords)[::-1]),1e-9))

	def test_edge_id_is_the_only_grouping_key(self):
		records=[
			("edge-b",LineString([(0,0),(100,0)])),
			("edge-a",LineString([(0,0),(100,0)])),
			("edge-a",LineString([(0,10),(100,10)])),
			("edge-a",LineString([(0,20),(100,20)])),
		]
		groups=build_edge_axes(records,sample_spacing_m=50)
		self.assertEqual(list(groups),["edge-a","edge-b"])
		axis_a,audit_a=groups["edge-a"]
		axis_b,audit_b=groups["edge-b"]
		self.assertCoordsAlmostEqual(list(axis_a.coords),[
			(0,10),(50,10),(100,10),
		])
		self.assertEqual(audit_a.input_lines,3)
		self.assertTrue(axis_b.equals_exact(records[0][1],0))
		self.assertEqual(audit_b.input_lines,1)

	def test_missing_edge_id_is_rejected(self):
		with self.assertRaisesRegex(ValueError,"edge_id fehlt"):
			build_edge_axes([(None,LineString([(0,0),(1,0)]))])
	def test_invalid_inputs_fail_explicitly(self):
		with self.assertRaisesRegex(ValueError,"Mindestens"):
			build_mean_axis([])
		with self.assertRaisesRegex(TypeError,"LineString"):
			build_mean_axis(["not a geometry"])
		with self.assertRaisesRegex(ValueError,"Abtastabstand"):
			build_mean_axis([LineString([(0,0),(1,0)]),
				LineString([(0,1),(1,1)])],sample_spacing_m=0)


if __name__=="__main__":
	unittest.main()
