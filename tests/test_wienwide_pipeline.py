"""Regressionen für Wienweite Kachel- und Datenpipeline ohne externe Dienste."""
from collections import Counter
import os
from zipfile import ZipFile
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from shapely import intersection as exact_intersection, union_all
from shapely.errors import GEOSException
from shapely.geometry import LineString, Point, Polygon, box, mapping
from shapely.ops import transform

from scripts.assign_gip_section_areas import partition, _samples
from scripts.wienwide_grid import (
	TO_METRIC, tile_id, tile_bounds, plan, build_manifest,
	read_manifest, write_manifest, checksum,
)
from scripts.wienwide_gip import (
	AXES,NODES,REPORT,urls_for_tile,build_index,validated_wfs,
	connect as connect_gip,
)
from scripts.wienwide_street import save_street_tile, load_street_tile
from scripts.diagnose_wien_voronoi import capture
from scripts.export_fmzk_strassenraum import STREET_CLASSIFICATION_VERSION
from scripts.wienwide_partition import (
	_polygon, _voronoi_intersection, graph_context, split_tile,
	run as partition_run, report_results,
)
from scripts.wienwide_benchmark import benchmark
from scripts.fetch_gip_sections import validate_layer


def fc(features):
	return {"type":"FeatureCollection","features":features}


class WienPipelineTests(unittest.TestCase):
	def setUp(self):
		self.tmp=tempfile.TemporaryDirectory()
		self.addCleanup(self.tmp.cleanup)
		self.root=Path(self.tmp.name)
		self.x,self.y=TO_METRIC(16.363,48.223)
		# Die AOI ist metrisch exakt, der dokumentierte GeoJSON-Rundweg
		# wird in den Tests dort genutzt, wo er tatsächlich vorkommt.
		self.aoi=box(self.x,self.y,self.x+500,self.y+300)
		from scripts.wienwide_grid import TO_METRIC as _project
		from pyproj import Transformer
		self.to_wgs=Transformer.from_crs("EPSG:31256","EPSG:4326",
			always_xy=True).transform
		self.geo_aoi=self.root/"aoi.geojson"
		self.geo_aoi.write_text(json.dumps(mapping(transform(self.to_wgs,self.aoi))),
			encoding="utf-8")
		self.plan_file=self.root/"grid.json"
		self.manifest=build_manifest(self.geo_aoi,size=250,halo=75)
		write_manifest(self.plan_file,self.manifest)
		self.gip_root=self.root/"gip"

	def test_plan_is_deterministic_and_covers_polygon(self):
		cells=plan(self.aoi,size=250,halo=75)
		self.assertGreaterEqual(len(cells),4)
		composite=union_all([box(*t["bounds_31256"]).intersection(self.aoi)
			for t in cells])
		self.assertLess(self.aoi.symmetric_difference(composite).area, .0001)
		self.assertEqual(cells,[*sorted(cells,key=lambda t:(t["iy"],t["ix"]))])
		self.assertEqual(tile_bounds(-1,2,1000),(-1000,2000,0,3000))
		self.assertEqual(tile_id(-1,2),"x-000001_y+000002")
		read_manifest(self.plan_file)
		with self.assertRaises(FileExistsError):
			write_manifest(self.plan_file,self.manifest)
		self.geo_aoi.write_text(self.geo_aoi.read_text(encoding="utf-8")+" ",
			encoding="utf-8")
		with self.assertRaisesRegex(ValueError,"verändert"):
			read_manifest(self.plan_file)

	def _axes_nodes(self):
		# Achsen liegen rund um den AOI-Mittelpunkt und sind absichtlich
		# in vielen WFS-Kacheln identisch vorhanden.
		xc,yc=self.x+250,self.y+150
		axes=[
			("11","Querstraße",LineString([(self.x+20,yc),(xc,yc)]),"1","9"),
			("12","Querstraße",LineString([(xc,yc),(self.x+480,yc)]),"9","2"),
			("13","Quergasse",LineString([(xc,yc),(xc,self.y+285)]),"9","3"),
			("14","Quergasse",LineString([(xc,yc),(xc,self.y+15)]),"9","4"),
		]
		nodes=[
			("1",Point(self.x+20,yc)),("2",Point(self.x+480,yc)),
			("3",Point(xc,self.y+285)),("4",Point(xc,self.y+15)),
			("9",Point(xc,yc)),
		]
		a=[{"type":"Feature","properties":{
			"gip_objectid":gid,"name":name,"fow":3,
			"node_from":start,"node_to":end},
			"geometry":mapping(transform(self.to_wgs,line))}
			for gid,name,line,start,end in axes]
		n=[{"type":"Feature","properties":{"gip_objectid":gid,"name":""},
			"geometry":mapping(transform(self.to_wgs,point))}
			for gid,point in nodes]
		return a,n

	def _fragments(self, *, conflicting=False):
		axes,nodes=self._axes_nodes()
		for i,tile in enumerate(self.manifest["tiles"]):
			path=self.gip_root/tile["id"]
			path.mkdir(parents=True)
			changed=json.loads(json.dumps(axes))
			if conflicting and i==1:
				changed[0]["properties"]["name"]="Falsche Dublette"
			p1,p2=path/AXES,path/NODES
			p1.write_text(json.dumps(fc(changed)),encoding="utf-8")
			p2.write_text(json.dumps(fc(nodes)),encoding="utf-8")
			urls,_=urls_for_tile(tile,self.manifest["halo_m"],4000)
			report={"schema_version":1,"tile_id":tile["id"],
				"urls":urls,
				"sha256":{"achsen":checksum(p1),"knoten":checksum(p2)}}
			(path/REPORT).write_text(json.dumps(report),encoding="utf-8")

	def test_index_deduplicates_across_tiles_and_rejects_conflicting_gip(self):
		self._fragments()
		idx=self.root/"gip.sqlite"
		stats=build_index(self.plan_file,self.gip_root,idx)
		self.assertEqual(stats["achsen"],4)
		self.assertEqual(stats["knoten"],5)
		self.assertGreater(stats["voronoi_sites"],60)
		self.assertGreater(stats["duplikate_zusammengefuehrt"]["achsen"],0)
		with connect_gip(idx) as db:
			self.assertEqual(db.execute("SELECT COUNT(*) FROM axes").fetchone()[0],4)
			self.assertEqual(db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],5)
			# Der Kreuzungsknoten hat vier angeschlossene Achsen.
			cells=self.manifest["tiles"]
			found=False
			for tile in cells:
				_sites,_axes,intersections=graph_context(db,tile["bounds_31256"])
				found=found or any(p.distance(Point(self.x+250,self.y+150))<.01
					for p in intersections)
			self.assertTrue(found)
		with self.assertRaises(FileExistsError):
			build_index(self.plan_file,self.gip_root,idx)

	def test_gip_conflict_aborts_without_committing_sqlite(self):
		self._fragments(conflicting=True)
		idx=self.root/"bad.sqlite"
		with self.assertRaisesRegex(ValueError,
			"GIP-Achse 11 weicht von .* ab; Attribute: \\['name'\\]"):
			build_index(self.plan_file,self.gip_root,idx)
		self.assertFalse(idx.exists())

	def test_missing_fragment_blocks_source_catalog(self):
		self._fragments()
		first=self.manifest["tiles"][0]["id"]
		(self.gip_root/first/REPORT).unlink()
		with self.assertRaises(FileNotFoundError):
			build_index(self.plan_file,self.gip_root,self.root/"missing.sqlite")

	def test_tiled_voronoi_matches_original_v0_and_has_no_seams(self):
		xc,yc=self.x+250,self.y+150
		axes=[
			{"id":"11","name":"Querstraße","fow":3,"geometry":
				LineString([(self.x+20,yc),(xc,yc)]),"start":"1","end":"9"},
			{"id":"12","name":"Querstraße","fow":3,"geometry":
				LineString([(xc,yc),(self.x+480,yc)]),"start":"9","end":"2"},
			{"id":"13","name":"Quergasse","fow":3,"geometry":
				LineString([(xc,yc),(xc,self.y+285)]),"start":"9","end":"3"},
			{"id":"14","name":"Quergasse","fow":3,"geometry":
				LineString([(xc,yc),(xc,self.y+15)]),"start":"9","end":"4"},
		]
		nodes=[{"id":"9","geometry":Point(xc,yc)}]
		street=union_all([
			box(self.x+20,yc-7,self.x+480,yc+7),
			box(xc-7,self.y+15,xc+7,self.y+285),
		])
		original,unknown,base=partition(street,axes,nodes)
		site_coords,owners=_samples(axes,5)
		all_sites=[(i,*pair) for i,pair in zip(owners,site_coords)]
		global_assigned={axis["id"]:geom for axis,geom in original}
		all_per_gid={}
		all_unknown=Counter()
		all_parts=[]
		for tile in plan(self.aoi,size=250,halo=75):
			bounds=tile["bounds_31256"]
			x0,y0,x1,y1=bounds
			local_sites=[x for x in all_sites if
				x0-75<=x[1]<=x1+75 and y0-75<=x[2]<=y1+75]
			lookup={i:axes[i] for i,_,_ in local_sites}
			core=box(*bounds).intersection(self.aoi)
			assigned,rest,stat=split_tile(street,core,local_sites,lookup,
				[Point(xc,yc)] if Point(xc,yc).distance(core)<=7 else [])
			if not stat["strassenraum_m2"]:
				continue
			for gid,geom in assigned.items():
				all_per_gid.setdefault(gid,[]).append(geom)
				all_parts.append(geom)
			for group,geom in rest.items():
				all_unknown[group]+=geom.area
				all_parts.append(geom)
		all_geom=union_all(all_parts)
		self.assertLess(street.symmetric_difference(all_geom).area,.05)
		self.assertLess(sum(g.area for g in all_parts)-all_geom.area,.05)
		for gid,geom in global_assigned.items():
			tiled=union_all(all_per_gid.get(gid,[]))
			self.assertLess(geom.symmetric_difference(tiled).area,.05,
				f"Naht oder Zuordnung bei GIP {gid}")
		for group,geom in unknown:
			self.assertAlmostEqual(all_unknown[group],geom.area,delta=.05)

	def test_targeted_voronoi_diagnosis_preserves_metric_sources_and_zip(self):
		# Diagnose nur als lesbares WKB-ZIP: kein GeoJSON-Rundweg
		# und keine Änderungen an vorhandenen SQLite-Kacheln.
		origin=box(0,0,100,100)
		cells=[box(0,0,50,100),box(50,0,100,100)]
		owner=union_all(cells)
		remaining=box(0,0,40,100)
		axis={"id":"10466577","name":"Quellachse","fow":3,
			"geometry":LineString([(25,10),(25,90)])}
		out=self.root/"voronoi-10466577.zip"
		report=capture(out,tile_id="x+000008_y+000350",
			gid=axis["id"],axis=axis,owner=owner,remaining=remaining,
			cells=cells,mask=origin,core=origin,
			street_path=self.plan_file,manifest_path=self.plan_file)
		self.assertTrue(out.is_file())
		self.assertEqual(report["gip_id"],"10466577")
		self.assertEqual(report["anzahl_voronoi_einzelzellen"],2)
		self.assertEqual(report["geometrien"]["direkter_schnitt"]
			["flaeche_m2"],4000)
		self.assertEqual(report["geometrien"]["vereinigung_einzelschnitte"]
			["flaeche_m2"],4000)
		self.assertEqual(report["geometrien"]["fehlend_aus_voronoi"]
			["flaeche_m2"],0)
		with ZipFile(out) as archive:
			entries=archive.namelist()
			self.assertIn("diagnose.json",entries)
			self.assertIn("wkb/restmaske.wkb",entries)
			self.assertIn("wkb/voronoi_vereinigung.wkb",entries)
			self.assertIn("wkb/zellen/00000.wkb",entries)
			self.assertIn("wkb/einzelschnitte/00000.wkb",entries)
			from shapely.wkb import loads
			self.assertTrue(loads(archive.read("wkb/restmaske.wkb"))
				.equals(remaining))
			self.assertEqual(json.loads(archive.read("diagnose.json"))
				["gip_id"],"10466577")
		self.assertTrue(owner.equals(union_all(cells)))
		with self.assertRaises(FileExistsError):
			capture(out,tile_id="x+000008_y+000350",
				gid=axis["id"],axis=axis,owner=owner,remaining=remaining,
				cells=cells,mask=origin,core=origin,
				street_path=self.plan_file,manifest_path=self.plan_file)

	def test_voronoi_diagnostic_callback_sees_preoverlay_remaining(self):
		# Hook muss den tatsächlichen Restzustand der Partition
		# genau vor dem einzelnen Voronoi-Overlay bereitstellen.
		street=box(0,0,100,100)
		sites=[(1,25,50),(2,75,50)]
		axes={
			1:{"id":"10466577","name":"Links","fow":3,
				"geometry":LineString([(25,20),(25,80)])},
			2:{"id":"20000000","name":"Rechts","fow":3,
				"geometry":LineString([(75,20),(75,80)])},
		}
		captured=[]
		class Captured(Exception):
			pass
		def visit(axis,owner,remaining,cells,mask,core):
			captured.append((axis["id"],owner,remaining,len(cells),
				mask,core))
			raise Captured()
		with self.assertRaises(Captured):
			split_tile(street,street,sites,axes,[],
				diagnostic=visit)
		self.assertEqual(len(captured),1)
		gid,owner,remaining,n,mask,core=captured[0]
		self.assertEqual(gid,"10466577")
		self.assertTrue(owner.is_valid)
		self.assertTrue(remaining.equals(street))
		self.assertTrue(mask.equals(street))
		self.assertTrue(core.equals(street))
		self.assertGreater(n,0)

	def test_voronoi_nested_shells_rebuilds_exact_site_cell_intersections(self):
		# Der echte Abbruch hatte ~1200 m² außerhalb der noch
		# verfügbaren Fläche. Eine ungültige Gesamt-Intersection
		# darf nie mit make_valid in den Nachbarraum ausgreifen.
		cells=[box(0,0,50,100),box(50,0,100,100)]
		owner=union_all(cells)
		remaining=box(0,0,40,100)
		invalid=Polygon([(0,0),(100,0),(100,100),(0,100),
			(0,0),(0,30),(0,0)])
		self.assertFalse(invalid.is_valid)
		self.assertGreater(invalid.area,remaining.area)
		calls=[]
		def broken_global_overlay(left,right,**kwargs):
			if left is owner and not kwargs:
				calls.append("fehlerhafte-Gesamtintersection")
				return invalid
			calls.append("einzelzelle-oder-praezision")
			return exact_intersection(left,right,**kwargs)
		audit=[]
		with patch("scripts.wienwide_partition.intersection",
			side_effect=broken_global_overlay):
			candidate=_voronoi_intersection(owner,remaining,cells,
				"Voronoi 10466577",audit)
		self.assertTrue(candidate.is_valid)
		self.assertTrue(candidate.equals(remaining))
		self.assertAlmostEqual(candidate.area,4000)
		self.assertEqual(len(audit),1)
		self.assertIn("Einzelzellen",audit[0]["methode"])
		self.assertEqual(audit[0]["voronoi_einzelzellen"],2)
		self.assertEqual(audit[0]["precision_grid_m"],None)
		self.assertIn("außerhalb noch nicht zugeordneter Straßenraum",
			audit[0]["originalfehler"])
		self.assertLess(audit[0]["pruefung"]
			["ausserhalb_uebrigem_strassenraum_m2"],1e-8)
		self.assertLess(audit[0]["pruefung"]
			["fehlend_von_voronoi_zellen_m2"],1e-8)
		self.assertIn("fehlerhafte-Gesamtintersection",calls)
		self.assertEqual(calls.count("einzelzelle-oder-praezision"),4)

	def test_voronoi_alternative_missing_area_still_stops(self):
		cells=[box(0,0,50,100),box(50,0,100,100)]
		owner=union_all(cells)
		remaining=box(0,0,40,100)
		invalid=Polygon([(0,0),(100,0),(100,100),(0,100),
			(0,0),(0,30),(0,0)])
		short=box(0,0,10,100)
		def broken_overlay(left,right,**kwargs):
			if left is owner and not kwargs:
				return invalid
			return short if left is owner or left is cells[0] else Polygon()
		audit=[]
		with patch("scripts.wienwide_partition.intersection",
			side_effect=broken_overlay):
			with self.assertRaisesRegex(ValueError,
				"nicht sicher.*nicht vollständig"):
				_voronoi_intersection(owner,remaining,cells,
					"Voronoi 10466577",audit)
		self.assertEqual(audit,[])

	def test_voronoi_alternative_extra_area_still_stops(self):
		cells=[box(0,0,50,100),box(50,0,100,100)]
		owner=union_all(cells)
		remaining=box(0,0,40,100)
		invalid=Polygon([(0,0),(100,0),(100,100),(0,100),
			(0,0),(0,30),(0,0)])
		overextended=box(0,0,80,100)
		def broken_overlay(left,right,**kwargs):
			if left is owner and not kwargs:
				return invalid
			return overextended if left is owner or left is cells[0] else Polygon()
		audit=[]
		with patch("scripts.wienwide_partition.intersection",
			side_effect=broken_overlay):
			with self.assertRaisesRegex(ValueError,
				"nicht sicher.*außerhalb Quellflächen"):
				_voronoi_intersection(owner,remaining,cells,
					"Voronoi 10466577",audit)
		self.assertEqual(audit,[])

	def test_voronoi_fallback_precision_grid_only_after_failed_cells(self):
		cells=[box(0,0,50,100),box(50,0,100,100)]
		owner=union_all(cells)
		remaining=box(0,0,40,100)
		invalid=Polygon([(0,0),(100,0),(100,100),(0,100),
			(0,0),(0,30),(0,0)])
		calls=[]
		def broken_cells(left,right,**kwargs):
			if left is owner and not kwargs:
				return invalid
			if left is cells[0]:
				raise GEOSException("Ring edge missing (Einzelzelle)")
			if "grid_size" in kwargs:
				calls.append(kwargs["grid_size"])
			return exact_intersection(left,right,**kwargs)
		audit=[]
		with patch("scripts.wienwide_partition.intersection",
			side_effect=broken_cells):
			candidate=_voronoi_intersection(owner,remaining,cells,
				"Voronoi 10466577",audit)
		self.assertTrue(candidate.equals(remaining))
		self.assertEqual(calls,[1e-9,1e-9,1e-8])
		self.assertEqual(audit[0]["precision_grid_m"],1e-9)
		self.assertIn("Präzisionsraster",audit[0]["methode"])
		self.assertIn("außerhalb noch nicht zugeordneter Straßenraum",
			audit[0]["originalfehler"])

	@unittest.skipUnless(os.environ.get("WIEN_VORONOI_DIAG_ZIP"),
		"Reale Wiener WKB-Diagnose nur bei WIEN_VORONOI_DIAG_ZIP")
	def test_real_wien_persidisweg_nested_shells_preserves_microarea(self):
		# Reale nicht versionierte Quelldaten: lokale Diagnose-ZIP.
		# Die fehlerhafte normale GEOS-Intersection ergibt ~1200 m²,
		# die echte Schnittfläche der sieben Voronoi-Zellen ~0,000147 m².
		from shapely.wkb import loads
		with ZipFile(os.environ["WIEN_VORONOI_DIAG_ZIP"]) as archive:
			owner=loads(archive.read("wkb/voronoi_vereinigung.wkb"))
			remaining=loads(archive.read("wkb/restmaske.wkb"))
			cells=[loads(archive.read(f"wkb/zellen/{i:05d}.wkb"))
				for i in range(7)]
		self.assertTrue(owner.is_valid)
		self.assertTrue(remaining.is_valid)
		self.assertEqual(len(cells),7)
		self.assertAlmostEqual(owner.area,1200.880845259245,delta=.001)
		self.assertTrue(all(cell.is_valid for cell in cells))
		audit=[]
		candidate=_voronoi_intersection(owner,remaining,cells,
			"Voronoi 10466577",audit)
		self.assertIsNotNone(candidate)
		self.assertTrue(candidate.is_valid)
		self.assertAlmostEqual(candidate.area,.00014695537,delta=1e-8)
		self.assertLess(candidate.difference(remaining).area,1e-8)
		self.assertLess(candidate.difference(owner).area,1e-8)
		self.assertEqual(len(audit),1)
		self.assertIn("Einzelzellen",audit[0]["methode"])
		checks=audit[0]["pruefung"]
		self.assertLess(checks["fehlend_von_voronoi_zellen_m2"],1e-8)
		self.assertLess(checks["ausserhalb_uebrigem_strassenraum_m2"],1e-8)
		self.assertEqual(len(checks["kontrollraster"]),2)
		self.assertLess(checks["referenz_differenz_m2"],1e-8)

	def test_valid_voronoi_overlay_does_not_invoke_fallback(self):
		cells=[box(0,0,50,100),box(50,0,100,100)]
		owner=union_all(cells)
		remaining=box(0,0,40,100)
		audit=[]
		with patch("scripts.wienwide_partition.intersection",
			wraps=exact_intersection) as func:
			result=_voronoi_intersection(owner,remaining,cells,
				"Voronoi 10466577",audit)
		self.assertTrue(result.equals(remaining))
		self.assertEqual(audit,[])
		func.assert_called_once_with(owner,remaining)

	def test_voronoi_repair_preserves_polygon_and_two_clip_witnesses(self):
		# Nach einer Polygon-Overlay-Operation kann GEOS eine
		# doppelte Randkante erzeugen, ohne die Fläche zu ändern.
		reference=box(0,0,10,10)
		invalid=Polygon([(0,0),(10,0),(10,10),(0,10),
			(0,0),(0,5),(0,0)])
		self.assertFalse(invalid.is_valid)
		audit=[]
		geom=_polygon(invalid,"Voronoi 10466577",
			witnesses=(("Voronoi-Zellen",reference),
				("noch nicht zugeordneter Straßenraum",reference)),
			repair_events=audit)
		self.assertTrue(geom.is_valid)
		self.assertTrue(geom.equals(reference))
		self.assertEqual(len(audit),1)
		self.assertEqual(audit[0]["kontext"],"Voronoi 10466577")
		self.assertAlmostEqual(audit[0]["differenz_m2"],0)
		self.assertAlmostEqual(audit[0]["ausserhalb_pruefgeometrien_m2"]
			["Voronoi-Zellen"],0)

	def test_voronoi_large_area_change_aborts_before_assignment(self):
		# Ungültige doppelte Umrundung würde bei make_valid
		# 100 m² verlieren; keine automatische Korrektur.
		invalid=Polygon([(0,0),(10,0),(10,10),(0,10),
			(0,0),(10,0),(10,10),(0,10),(0,0)])
		self.assertFalse(invalid.is_valid)
		with self.assertRaisesRegex(ValueError,
			"Voronoi 10466577.*verändert Fläche"):
			_polygon(invalid,"Voronoi 10466577",
				witnesses=(("Voronoi-Zellen",box(0,0,10,10)),))

	def test_voronoi_repair_must_stay_inside_original_site_cell(self):
		invalid=Polygon([(0,0),(10,0),(10,10),(0,10),
			(0,0),(0,5),(0,0)])
		with self.assertRaisesRegex(ValueError,
			"Voronoi 10466577.*außerhalb Voronoi-Zellen"):
			_polygon(invalid,"Voronoi 10466577",
				witnesses=(("Voronoi-Zellen",box(0,0,9,10)),
					("noch nicht zugeordneter Straßenraum",
						box(0,0,10,10))))

	def test_invalid_voronoi_zero_area_is_not_silently_discarded(self):
		bowtie=Polygon([(0,0),(10,10),(0,10),(10,0),(0,0)])
		self.assertFalse(bowtie.is_valid)
		self.assertEqual(bowtie.area,0)
		with self.assertRaisesRegex(ValueError,"Nullfläche"):
			_polygon(bowtie,"Voronoi 10466577")

	def test_voronoi_real_partition_records_geos_overlay_repair(self):
		# In eine ansonsten reguläre Aufteilung ein topologisch
		# fehlerhaftes Randpolygon mit gleicher Fläche einschleusen.
		# Die GIP-ID und Flächenzuordnung dürfen nicht verloren gehen.
		core=box(0,0,100,100)
		street=core
		sites=[(1,25,50),(2,75,50)]
		axes={
			1:{"id":"10466577","name":"Test links","fow":3,
				"geometry":LineString([(25,20),(25,80)])},
			2:{"id":"20000000","name":"Test rechts","fow":3,
				"geometry":LineString([(75,20),(75,80)])},
		}
		source_polygon=_polygon
		injected=[]
		def damaged_overlay(g,label,**kwargs):
			if label=="Voronoi 10466577":
				self.assertEqual(g.geom_type,"Polygon")
				coords=list(g.exterior.coords)
				start,nextpoint=coords[:2]
				mid=((start[0]+nextpoint[0])/2,
					(start[1]+nextpoint[1])/2)
				g=Polygon(coords+[mid,start])
				self.assertFalse(g.is_valid)
				injected.append(label)
			return source_polygon(g,label,**kwargs)
		with patch("scripts.wienwide_partition._polygon",
			side_effect=damaged_overlay):
			assigned,unresolved,stats=split_tile(
				street,core,sites,axes,[])
		self.assertEqual(injected,["Voronoi 10466577"])
		self.assertIn("10466577",assigned)
		self.assertTrue(assigned["10466577"].is_valid)
		self.assertAlmostEqual(stats["strassenraum_m2"],10000)
		self.assertLess(stats["fehlend_m2"],.05)
		self.assertLess(stats["overlap_m2"],.05)
		self.assertEqual(len(stats["geometrie_reparaturen"]),1)
		self.assertEqual(stats["geometrie_reparaturen"][0]
			["kontext"],"Voronoi 10466577")
		self.assertGreaterEqual(stats["zugeordnet_m2"],0)
		self.assertGreaterEqual(stats["ungeklaert_m2"],0)

	def test_wfs_bbox_superset_filters_outside_hulls_without_losing_counts(self):
		# WFS BBOX liefert ein Kandidatensuperset. Auch ein um
		# die BBOX verlaufendes Objekt mit Hüllrechteck-Treffer
		# darf NICHT als benachbarte Achse in den GIP-Index.
		tile=self.manifest["tiles"][0]
		_,bounds=urls_for_tile(tile,75,4000)
		x0,y0,x1,y1=bounds
		from pyproj import Transformer
		to_geo=Transformer.from_crs("EPSG:3857","EPSG:4326",
			always_xy=True)
		def line(gid,points):
			return {"type":"Feature","id":f"WFS.axis.{gid}",
				"geometry":{"type":"LineString","coordinates":[
					list(to_geo.transform(x,y)) for x,y in points]},
				"properties":{"GIP_OBJECTID":gid,
					"FEATURENAME":"Gasse","NODEFROM_OBJECTID":11,
					"NODETO_OBJECTID":12,"FOW":3}}
		u_shape=[(x0-100,y0-100),(x0-100,y1+100),
			(x1+100,y1+100),(x1+100,y0-100)]
		inside=line(111,[(x0+40,y0+40),(x0+80,y0+40)])
		outside=line(777,u_shape)
		doc=fc([outside,inside])
		doc["totalFeatures"]=2
		raw=json.dumps(doc).encode("utf-8")
		with self.assertRaisesRegex(ValueError,"außerhalb der WFS-BBOX"):
			validate_layer(raw,"achsen",bounds,max_features=4000)
		_,view,summary=validated_wfs(raw,"achsen",bounds,
			max_features=4000)
		self.assertEqual(summary["antwort_features"],2)
		self.assertEqual(summary["anzahl"],1)
		self.assertEqual(summary["wfs_bbox_ausgeschlossen_anzahl"],1)
		self.assertEqual(summary["wfs_bbox_ausgeschlossen"][0]["gip_id"],"777")
		self.assertTrue(
			summary["wfs_bbox_ausgeschlossen"][0]["huellrechteck_schneidet"])
		self.assertEqual(
			[x["properties"]["gip_objectid"] for x in view["features"]],["111"])
		self.assertEqual(
			json.loads(json.dumps(view["features"][0]["geometry"])),
			inside["geometry"])
		# Unvollständige WFS-Antworten müssen trotz Filterung
		# unverändert und VOR dem Filtern abgelehnt werden.
		doc["totalFeatures"]=3
		with self.assertRaisesRegex(ValueError,"unvollständige Antwort"):
			validated_wfs(json.dumps(doc).encode(),"achsen",bounds,
				max_features=4000)

	def test_wfs_distance_outside_bbox_is_audited_not_tolerance_escalated(self):
		# Beide beim Realabruf beobachteten Fälle: 0,059 m und
		# 1,309 m Abstand in EPSG:3857, ohne Hüllentreffer.
		tile=self.manifest["tiles"][0]
		_,bounds=urls_for_tile(tile,75,4000)
		x0,y0,x1,y1=bounds
		from pyproj import Transformer
		to_geo=Transformer.from_crs("EPSG:3857","EPSG:4326",
			always_xy=True)
		def sample(kind,distance):
			if kind=="achsen":
				geom={"type":"LineString","coordinates":[
					list(to_geo.transform(x0-distance,y0+50)),
					list(to_geo.transform(x0-distance,y0+80))]}
			else:
				geom={"type":"Point","coordinates":
					list(to_geo.transform(x0-distance,y0+50))}
			return json.dumps(fc([{
				"type":"Feature","id":"WFS.10023340","geometry":geom,
				"properties":{"GIP_OBJECTID":10023340,
					"NODEFROM_OBJECTID":11,"NODETO_OBJECTID":12,"FOW":3},
			}])).encode("utf-8")
		for distance in (.059,1.309,30.,100.):
			with self.subTest(distance=distance):
				raw=sample("achsen",distance)
				with self.assertRaisesRegex(ValueError,"außerhalb der WFS-BBOX"):
					validate_layer(raw,"achsen",bounds,max_features=4000)
				_,view,summary=validated_wfs(raw,"achsen",bounds,
					max_features=4000)
				self.assertEqual(view["features"],[])
				self.assertEqual(summary["antwort_features"],1)
				self.assertEqual(summary["anzahl"],0)
				self.assertEqual(
					summary["wfs_bbox_ausgeschlossen"][0]["gip_id"],
					"10023340")
				self.assertAlmostEqual(
					summary["wfs_bbox_ausgeschlossen"][0]
						["abstand_epsg3857_m"],
					distance,delta=.0001)
				self.assertFalse(
					summary["wfs_bbox_ausgeschlossen"][0]
						["huellrechteck_schneidet"])
		# Knoten außerhalb des Halos werden ebenso aussortiert,
		# NICHT ohne räumliche Prüfung in den Graph aufgenommen.
		_,view,summary=validated_wfs(sample("knoten",.059),
			"knoten",bounds,max_features=4000)
		self.assertEqual(view["features"],[])
		self.assertEqual(summary["wfs_bbox_ausgeschlossen_anzahl"],1)
		# Die alte optionale numerische Toleranz lässt sich
		# weiterhin nicht unbegrenzt erweitern.
		with self.assertRaisesRegex(ValueError,"0,25 m"):
			validate_layer(sample("achsen",1.309),"achsen",bounds,
				bbox_numeric_tolerance_m=1.)

	def test_wfs_excluded_candidates_persist_in_report_and_cache(self):
		from scripts.wienwide_gip import fetch_all
		from urllib.parse import parse_qs,urlparse
		from pyproj import Transformer
		tile=self.manifest["tiles"][0]
		_,bounds=urls_for_tile(tile,75,4000)
		x0,y0,x1,y1=bounds
		to_geo=Transformer.from_crs("EPSG:3857","EPSG:4326",
			always_xy=True)
		def feat(gid,xoff,kind="achsen"):
			p1=list(to_geo.transform(x0+xoff,y0+50))
			p2=list(to_geo.transform(x0+xoff,y0+80))
			return {"type":"Feature","id":f"WFS.{gid}",
				"geometry":{"type":"LineString","coordinates":[p1,p2]}
					if kind=="achsen" else
					{"type":"Point","coordinates":p1},
				"properties":{"GIP_OBJECTID":gid,"FEATURENAME":"Test",
					"NODEFROM_OBJECTID":11,"NODETO_OBJECTID":12,"FOW":3}}
		def downloader(url):
			is_axis="STRASSENGRAPHOGD" in url
			features=[feat(10,25)]+[feat(10023340,-1.309)] if is_axis else [
				feat(11,25,"knoten")]
			doc=fc(features)
			doc["totalFeatures"]=len(features)
			return json.dumps(doc).encode()
		root=self.root/"gip_cache"
		records=fetch_all(self.plan_file,root,limit_tiles=1,
			downloader=downloader)
		self.assertEqual(records,[{"tile":tile["id"],"cache":False}])
		folder=root/tile["id"]
		report=json.loads((folder/REPORT).read_text())
		self.assertEqual(report["wfs_antwort_features"]["achsen"],2)
		self.assertEqual(report["anzahl"]["achsen"],1)
		excluded=report["wfs_bbox_ausgeschlossen"]["achsen"]
		self.assertEqual(excluded["anzahl"],1)
		self.assertEqual(excluded["gip_ids_mit_abstand"][0]["gip_id"],"10023340")
		self.assertAlmostEqual(
			excluded["gip_ids_mit_abstand"][0]["abstand_epsg3857_m"],
			1.309,delta=.0001)
		kept=json.loads((folder/AXES).read_text())["features"]
		self.assertEqual([x["properties"]["gip_objectid"] for x in kept],["10"])
		def no_network(_):
			raise AssertionError("Bestehenden gültigen Cache nicht neu laden")
		reused=fetch_all(self.plan_file,root,limit_tiles=1,
			downloader=no_network)
		self.assertEqual(reused,[{"tile":tile["id"],"cache":True}])

	def test_verified_empty_wfs_and_incorrect_counts(self):
		tile=self.manifest["tiles"][0]
		_,bounds=urls_for_tile(tile,75,4000)
		empty=json.dumps(fc([])).encode()
		_,view,stats=validated_wfs(empty,"achsen",bounds,
			max_features=4000)
		self.assertEqual(stats["anzahl"],0)
		self.assertEqual(view["features"],[])
		doc=fc([])
		doc["numberMatched"]=3
		with self.assertRaisesRegex(ValueError,"trotz leerer Kachel"):
			validated_wfs(json.dumps(doc).encode(),"achsen",bounds,
				max_features=4000)
		doc=fc([])
		doc["crs"]={"type":"name","properties":{"name":"EPSG:3857"}}
		with self.assertRaisesRegex(ValueError,"nicht unterstütztes Quell-CRS"):
			validated_wfs(json.dumps(doc).encode(),"achsen",bounds,
				max_features=4000)

	def test_empty_street_requires_explicit_verified_status(self):
		from shapely.geometry import Polygon
		from scripts.wienwide_partition import split_tile
		empty=Polygon()
		out=self.root/"empty.sqlite"
		with self.assertRaisesRegex(ValueError,"Leere"):
			save_street_tile(out,empty,{"schema_version":"1",
				"crs":"EPSG:31256"})
		save_street_tile(out,empty,{"schema_version":"1",
			"crs":"EPSG:31256",
			"strassenraum_regel_version":STREET_CLASSIFICATION_VERSION,
			"nachweislich_ohne_strassenraum":True},
			allow_empty=True)
		loaded=load_street_tile(out,self.aoi)
		self.assertTrue(loaded.is_empty)
		parts,rest,stats=split_tile(loaded,self.aoi,[],{},[])
		self.assertEqual(parts,{})
		self.assertEqual(rest,{})
		self.assertEqual(stats["zugeordnet_m2"],0)
		self.assertEqual(stats["strassenraum_m2"],0)
		self.assertEqual(stats["ungeklaert_m2"],0)

	def test_sqlite_result_resume_and_full_area_audit(self):
		self._fragments()
		gip=self.root/"gip.sqlite"
		build_index(self.plan_file,self.gip_root,gip)
		street_root=self.root/"street"
		# Benutze dieselbe georeferenzierte AOI-Geometrie wie die
		# Produktionsroutine nach GeoJSON-Einlesen; ein künstlich
		# zweiter Referenzumweg erzeugt sonst Versatz am Außenrand.
		_,actual_aoi=read_manifest(self.plan_file)
		for tile in self.manifest["tiles"]:
			core=box(*tile["bounds_31256"])
			street=core.intersection(actual_aoi)
			if street.area<=0:continue
			path=street_root/tile["id"]/"street.sqlite"
			save_street_tile(path,street,{"schema_version":"1",
				"crs":"EPSG:31256","tile_id":tile["id"],
				"strassenraum_regel_version":STREET_CLASSIFICATION_VERSION})
			self.assertAlmostEqual(load_street_tile(path,core).area,street.area)
		output=self.root/"out.sqlite"
		partial=partition_run(self.plan_file,gip,street_root,output,
			limit_tiles=1)
		self.assertIn("PARTIELL",partial["status"])
		report=partition_run(self.plan_file,gip,street_root,output)
		self.assertEqual(report["kacheln"],len(self.manifest["tiles"]))
		self.assertAlmostEqual(report["strassenraum_m2"],
			self.manifest["aoi_area_m2"],delta=.1)
		self.assertAlmostEqual(report["bilanzdifferenz_m2"],0,delta=.05)
		self.assertGreater(report["geometrisch_eindeutige_gip_ids"],0)
		resumed=partition_run(self.plan_file,gip,street_root,output)
		self.assertEqual(report["abschnitte_m2"],resumed["abschnitte_m2"])
		bench=benchmark(self.plan_file,inputs=self.root/"unused",
			fragments=self.gip_root,street_root=street_root,
			gip_index=gip,partition_db=output)
		self.assertEqual(bench["anzahl_kacheln"],len(self.manifest["tiles"]))
		self.assertEqual(bench["quellabdeckung"]["gip_bericht_vorhanden"],
			len(self.manifest["tiles"]))
		self.assertEqual(bench["partition"]["status"],"vollständig")
		self.assertAlmostEqual(bench["partition"]["gesamtbilanz"]["strassenraum_m2"],
			report["strassenraum_m2"],delta=.01)


if __name__=="__main__":
	unittest.main()
