"""Metrischer BEV-MVT-Kataster für Wien ohne GeoJSON-Rückprojektion."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shapely import union_all
from shapely.geometry import box
from scripts.wienwide_kataster import read_native_kataster_masks
from scripts.wienwide_street import (
	build_tile,load_street_tile,check_existing_tile,
	save_street_tile,run as street_run,
)
from scripts.wienwide_grid import checksum
from scripts.export_fmzk_strassenraum import STREET_CLASSIFICATION_VERSION


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
			(2,69,"Zusatzfläche",box(30,10,35,20)),
			(3,69,"Sehr schmaler Straßenrand",
				box(11,20,11.008,21))]
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
			"zoom":16,"fmzk_kern_klassen":[21,23,24,25,33,39],
			"bbox_lon_lat":self.bbox,
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

	def test_old_kataster_core_codes_are_rejected(self):
		self.report.pop("fmzk_kern_klassen")
		(self.kat/"kataster_bericht.json").write_text(
			json.dumps(self.report), encoding="utf-8")
		with self.assertRaisesRegex(ValueError, "veralteten FMZK-Kernklassen"):
			read_native_kataster_masks(self.kat,self.clip,self.fmzk,
				self.manifest,self.cache)

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

	def test_resume_verifies_aoi_and_every_cached_bev_source(self):
		aoi=box(0,0,100,100)
		tile={"id":"first","bounds_31256":[0,0,100,100]}
		input_root=self.root/"inputs"
		folder=input_root/"first"
		folder.mkdir(parents=True)
		fmzk=folder/"fmzk.gpkg"
		fmzk.write_bytes(b"fmzk source")
		kat=folder/"kataster"
		kat.mkdir()
		report=kat/"kataster_bericht.json"
		report.write_text(json.dumps(self.report),encoding="utf-8")
		source=self.cache/"tiles"/"16"/"35000"/"23000.pbf"
		meta={
			"schema_version":"1","crs":"EPSG:31256",
			"tile_id":"first","aoi_area_m2":10000,
			"strassenraum_m2":100,
			"halo_m":75,"fmzk_sha256":checksum(fmzk),
			"strassenraum_regel_version":STREET_CLASSIFICATION_VERSION,
			"kataster_bericht_sha256":checksum(report),
			"kataster_status":{"bev_cache_sha256":{
				"16/35000/23000":checksum(source)}},
		}
		output=self.root/"out"
		street=output/"first"/"street.sqlite"
		save_street_tile(street,box(10,10,20,20),meta)
		with patch("scripts.wienwide_street.read_manifest",
			return_value=({"tiles":[tile],"halo_m":75},aoi)), patch(
			"scripts.wienwide_street.build_tile",
			side_effect=AssertionError("Darf Cache nicht neu berechnen")):
			res=street_run(self.root/"raster.json",input_root,output,
				cache_dir=self.cache)
		self.assertEqual(len(res),1)
		self.assertTrue(res[0]["cache"])
		self.assertEqual(res[0]["area_m2"],100)
		self.assertEqual(check_existing_tile(tile,aoi,input_root=input_root,
			output_root=output,halo=75,cache_dir=self.cache)["area_m2"],100)
		with self.assertRaisesRegex(ValueError,"anderer AOI"):
			check_existing_tile(tile,box(0,0,99,100),input_root=input_root,
				output_root=output,halo=75,cache_dir=self.cache)
		with self.assertRaisesRegex(ValueError,"anderem Halo"):
			check_existing_tile(tile,aoi,input_root=input_root,
				output_root=output,halo=80,cache_dir=self.cache)
		fmzk.write_bytes(b"changed fmzk")
		with self.assertRaisesRegex(ValueError,"verändert"):
			check_existing_tile(tile,aoi,input_root=input_root,
				output_root=output,halo=75,cache_dir=self.cache)
		fmzk.write_bytes(b"fmzk source")
		source.write_bytes(b"changed BEV")
		with self.assertRaisesRegex(ValueError,"BEV-Rohkachel"):
			check_existing_tile(tile,aoi,input_root=input_root,
				output_root=output,halo=75,cache_dir=self.cache)
		self.assertTrue(street.exists())

	def test_resume_rejects_old_method_even_with_unchanged_fmzk(self):
		aoi=box(0,0,100,100)
		tile={"id":"first","bounds_31256":[0,0,100,100]}
		street=self.root/"out"/"first"/"street.sqlite"
		save_street_tile(street,box(10,10,20,20),{
			"schema_version":"1","crs":"EPSG:31256",
			"tile_id":"first","aoi_area_m2":10000,
			"strassenraum_m2":100,"halo_m":75,
			"strassenraum_regel_version":"alte-regel",
		})
		with self.assertRaisesRegex(ValueError, "alter Klassifikationsregel"):
			check_existing_tile(tile,aoi,input_root=self.root/"inputs",
				output_root=self.root/"out",halo=75,cache_dir=self.cache)

	def test_wienwide_street_includes_class_25_outside_bev_mask(self):
		inputs=self.root/"inputs"
		folder=inputs/"first"
		folder.mkdir(parents=True)
		(folder/"fmzk.gpkg").write_bytes(b"synthetic fmzk")
		kat=folder/"kataster"
		kat.mkdir()
		(kat/"kataster_bericht.json").write_text(
			json.dumps(self.report),encoding="utf-8")
		aoi=box(0,0,100,100)
		tile={"id":"first","bounds_31256":[0,0,100,100]}
		fmzk=[(1,21,"Fahrbahn",box(10,10,20,20)),
			(2,25,"Gehweg, Radweg",box(60,60,80,62))]
		with patch("scripts.wienwide_street.load_polygons",
			return_value=(fmzk,self.manifest,box(-50,-50,150,150),[])), patch(
			"scripts.wienwide_street.read_native_kataster_masks",
			return_value=(box(10,10,20,20),box(40,40,50,50),{})):
			result=build_tile(tile,aoi,root=inputs,out=self.root/"output_25",
				halo=75,cache_dir=self.cache)
		self.assertAlmostEqual(result["strassenraum_m2"],140)
		geom=load_street_tile(
			self.root/"output_25"/"first"/"street.sqlite",aoi)
		self.assertAlmostEqual(geom.area,140)
		self.assertAlmostEqual(geom.intersection(box(60,60,80,62)).area,40)

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
			return_value=(union_all([
				self.slim,box(30,10,35,20)]),
				box(40,10,50,20),
				{"betroffene_grundstuecke":1,"quelle":"metric"})) as native:
			result=build_tile(tile,aoi,root=inputs,out=self.root/"out",
				halo=75,cache_dir=self.cache)
		native.assert_called_once()
		self.assertEqual(native.call_args.args[0],kat)
		self.assertEqual(native.call_args.args[-1],self.cache)
		self.assertAlmostEqual(result["strassenraum_m2"],150+.008,
			delta=.001)  # 100 m² Kern + 50 m² Zusatz + 0,008 m² Rand
		stored=load_street_tile(
			self.root/"out"/"first"/"street.sqlite",aoi)
		self.assertAlmostEqual(stored.area,150+.008,delta=.001)


if __name__=="__main__":
	unittest.main()
