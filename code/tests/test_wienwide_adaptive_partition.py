"""Adaptive 1-km-Wienkacheln ohne geänderten 5-m-Abtastabstand.

Die Begrenzung der Voronoi-Sites darf nur das interne Rechenraster
verkleinern, niemals eine abgeschlossene Elternkachel oder die
geometrische Straßenraumzuordnung verändern.
"""
import unittest
from unittest.mock import patch

from shapely.geometry import LineString, box

from scripts.wienwide_partition import (
	_split_overfull_tile, split_tile,
)


class AdaptiveWienPartitionTests(unittest.TestCase):
	def test_overfull_tile_is_merged_without_area_loss_or_seams(self):
		# Eine reale 5-m-Stützpunktreihe einer globalen GIP-Achse.
		core=box(0,0,1000,1000)
		street=box(0,480,1000,520)
		axis={"id":"axis-1","name":"Teststraße","fow":3,
			"geometry":LineString([(0,500),(1000,500)])}
		sites=[(1,i*5+2.5,500.) for i in range(200)]
		axes={1:axis}
		# Der globale Schnitt mit 200 Sites ist die fachliche Referenz.
		with patch("scripts.wienwide_partition.MAX_SITES",10000):
			original,rest,baseline=split_tile(street,core,sites,axes,[],
				exclude_junctions=False,all_fow=True)
		calls=[]
		def context(_db,bounds,*,halo=75):
			calls.append((bounds,halo))
			x0,y0,x1,y1=bounds
			local=[s for s in sites if x0-halo<=s[1]<=x1+halo
				and y0-halo<=s[2]<=y1+halo]
			return local,{1:axis} if local else {},[]
		with patch("scripts.wienwide_partition.graph_context",side_effect=context), \
				patch("scripts.wienwide_partition.MAX_SITES",120):
			actual,unresolved,stats,leaves,depth=_split_overfull_tile(
				object(),street,core,core.bounds,halo=75,
				exclude_junctions=False,all_fow=True,
				sites=sites,axes=axes,nodes=[])
		self.assertGreater(leaves,1)
		self.assertGreaterEqual(depth,1)
		self.assertTrue(calls)
		self.assertTrue(all(halo==75 for _bounds,halo in calls))
		self.assertEqual(set(original),set(actual))
		self.assertEqual(set(rest),set(unresolved))
		for gid,shape in original.items():
			self.assertLess(actual[gid].symmetric_difference(shape).area,.05)
		self.assertAlmostEqual(stats["strassenraum_m2"],
			baseline["strassenraum_m2"],delta=.05)
		self.assertAlmostEqual(stats["zugeordnet_m2"],
			baseline["zugeordnet_m2"],delta=.05)
		self.assertLess(stats["overlap_m2"],.05)
		self.assertLess(stats["fehlend_m2"],.05)
		self.assertLess(stats["ausserhalb_m2"],.05)
		self.assertEqual(stats["sites"],200)
		self.assertEqual(stats["adaptive_voronoi"]["abtastabstand_m"],5)
		self.assertEqual(stats["adaptive_voronoi"]["halo_m"],75)
		self.assertEqual(stats["adaptive_voronoi"]["teilstuecke"],leaves)


if __name__=="__main__":
	unittest.main()
