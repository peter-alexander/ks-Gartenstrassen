"""Metrischer BEV-MVT-Kataster für Wien ohne GeoJSON-Rückprojektion."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shapely.geometry import box
from scripts.wienwide_kataster import read_native_kataster_masks
from scripts.wienwide_street import build_tile,load_street_tile


class WienwideKatasterTests(unittest.TestCase):
	def setUp(self):
		self.temp=tempfile.TemporaryDirectory()
		self.addCleanup(self.temp.cleanup)
		self.root=Path(self.temp.name)
		self.kat=self.root/"kataster"
		self.kat.mkdir()
		self.cache=self.root/"cache"
		self.tiles=[(16,35000,23000)]
		for z,x,y in self.tiles:
			f=self.cache/"tiles"/str(z)/str(x)/f"{y}.pbf"
			f.parent.mkdir(parents=True,exist_ok=True)
			f.write_bytes(b"cached source, offline test")
		self.bbox=[16.35,48.20,16.36,48.21]
		self.manifest={"bbox_lon_lat":self.bbox}
		self.clip=box(0,0,100,100)
		self.fmzk=[(1,21,"Straßenkern",box(10,10,20,20)),
			(2,69,"Zusatzfläche",box(30,10,35,20))]
		self.parcels={("01002","1"):box(0,0,60,60)}
		# Fragile schmale Fläche 0,08 m² (>0,05 m²):
		# muss im METRISCHEN ORIGINAL erhalten bleiben.
		self.slim=box(11,11,11.008,21)
		self.nfl=[
			({"ns":95},self.slim),
			({"ns":65},box(30,10,35,20)),
			({"ns":52},box(40,10,50,20)),
			({"ns":65},box(30,10,35,20)),  # MVT-Überlappung
			({"ns":95},box(40,40,40.001,45)),  # nur 0,005 m²
		]
		self._report()

	def _report(self, *, grundstuecke=1, tiles=None):
		self.report={
			"zoom":16,"bbox_lon_lat":self.bbox,
			"grundstuecke":grundstuecke,
			"tiles_abgerufen":[list(t) for t in (tiles or self.tiles)]}
		(self.kat/"kataster_bericht.json").write_text(
			json.dumps(self.report),encoding="utf-8")

	def test_native_mvt_preserves_thin_polygon_and_deduplicates_tiles(self):
		with patch("scripts.wienwide_kataster.read_tiles",
			return_value=(self.parcels,self.nfl,self.tiles)) as mocked:
			street,other,stats=read_native_kataster_masks(
				self.kat,self.clip,self.fmzk,self.manifest,self.cache)
		mocked.assert_called_once_with(
			self.bbox,self.cache,offline=True,max_tiles=120)
		self.assertAlmostEqual(street.area,self.slim.area+50,delta=.0001)
		self.assertAlmostEqual(other.area,100,delta=.0001)
		self.assertAlmostEqual(street.intersection(self.slim).area,.08,
			delta=.0001)
		self.assertEqual(stats["nfl_fragmente"],4)
		self.assertEqual(stats["nfl_fragmente_bis_0_05m2_nicht_uebernommen"],1)
		self.assertEqual(stats["betroffene_grundstuecke"],1)
		self.assertEqual(stats["bev_cache_anzahl"],1)
		self.assertIn("16/35000/23000",stats["bev_cache_sha256"])
		self.assertIn("direkt-metrisch",stats["quelle"])

	def test_offline_cache_required_even_with_valid_report(self):
		p=self.cache/"tiles"/"16"/"35000"/"23000.pbf"
		p.unlink()
		with self.assertRaisesRegex(FileNotFoundError,"BEV-Rohkachel fehlt"):
			read_native_kataster_masks(self.kat,self.clip,self.fmzk,
				self.manifest,self.cache)

	def test_rejects_wrong_parcel_count_or_stale_bev_tiling(self):
		self._report(grundstuecke=2)
		with patch("scripts.wienwide_kataster.read_tiles",
			return_value=(self.parcels,self.nfl,self.tiles)):
			with self.assertRaisesRegex(ValueError,"1 statt 2"):
				read_native_kataster_masks(self.kat,self.clip,self.fmzk,
					self.manifest,self.cache)
		self._report()
		with patch("scripts.wienwide_kataster.read_tiles",
			return_value=(self.parcels,self.nfl,[(16,35001,23000)])):
			with self.assertRaisesRegex(ValueError,"Kachelliste"):
				read_native_kataster_masks(self.kat,self.clip,self.fmzk,
					self.manifest,self.cache)

	def test_invalid_usage_code_aborts_not_silently_ignored(self):
		invalid=[({"ns":"?"},box(10,10,15,15))]+self.nfl
		with patch("scripts.wienwide_kataster.read_tiles",
			return_value=(self.parcels,invalid,self.tiles)):
			with self.assertRaisesRegex(ValueError,"Unbekannter nfl-Code"):
				read_native_kataster_masks(self.kat,self.clip,self.fmzk,
					self.manifest,self.cache)

	def test_wienwide_street_build_uses_only_metric_cache(self):
		inputs=self.root/"inputs"
		folder=inputs/"first"
		folder.mkdir(parents=True)
		(folder/"fmzk.gpkg").write_bytes(b"test fmzk")
		kat=folder/"kataster"
		kat.mkdir()
		(kat/"kataster_bericht.json").write_text(json.dumps(
			self.report),encoding="utf-8")
		aoi=box(0,0,100,100)
		clip=box(-50,-50,150,150)
		tile={"id":"first","bounds_31256":[0,0,100,100]}
		# Ein echter Build lädt Daten aus dem GeoPackage;
		# der Test prüft explizit die Verdrahtung nach dem Laden.
		with patch("scripts.wienwide_street.load_polygons",
			return_value=(self.fmzk,self.manifest,clip,[])), patch(
			"scripts.wienwide_street.read_native_kataster_masks",
			return_value=(self.slim,box(40,10,50,20),
				{"betroffene_grundstuecke":1,"quelle":"metric"})) as native:
			result=build_tile(tile,aoi,root=inputs,out=self.root/"out",
				halo=75,cache_dir=self.cache)
		native.assert_called_once()
		self.assertEqual(native.call_args.args[0],kat)
		self.assertEqual(native.call_args.args[-1],self.cache)
		self.assertAlmostEqual(result["strassenraum_m2"],100+.08,
			delta=.001)  # Kern 100 m² + schmaler BEV-nfl-Rand
		stored=load_street_tile(
			self.root/"out"/"first"/"street.sqlite",aoi)
		self.assertAlmostEqual(stored.area,100+.08,delta=.001)


if __name__=="__main__":
	unittest.main()
