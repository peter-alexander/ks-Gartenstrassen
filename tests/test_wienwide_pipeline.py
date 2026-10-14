"""Regressionen für Wienweite Kachel- und Datenpipeline ohne externe Dienste."""
from collections import Counter
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from shapely import union_all
from shapely.geometry import LineString, Point, box, mapping
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
from scripts.wienwide_partition import (
	graph_context, split_tile, run as partition_run, report_results,
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
		with self.assertRaisesRegex(ValueError,"Konflikt"):
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

	def test_wfs_bbox_envelope_only_axis_is_valid_but_audited(self):
		# Eine U-förmige vollständige WFS-Achse UM die BBOX,
		# ohne die BBOX selbst zu schneiden. WFS-BBOX liefert
		# mit räumlichem Index auch solche Hüllen-Treffer.
		# Unser wienweiter Abruf darf sie nicht wegwerfen.
		tile=self.manifest["tiles"][0]
		_,bounds=urls_for_tile(tile,75,4000)
		x0,y0,x1,y1=bounds
		u_shape=[(x0-100,y0-100),(x0-100,y1+100),
			(x1+100,y1+100),(x1+100,y0-100)]
		from pyproj import Transformer
		to_geo=Transformer.from_crs("EPSG:3857","EPSG:4326",
			always_xy=True)
		def payload(points):
			coords=[list(to_geo.transform(x,y)) for x,y in points]
			return json.dumps(fc([{
				"type":"Feature","id":"WFS.axis.777",
				"geometry":{"type":"LineString","coordinates":coords},
				"properties":{
					"GIP_OBJECTID":777,"FEATURENAME":"Umweg",
					"NODEFROM_OBJECTID":11,"NODETO_OBJECTID":12,
					"FOW":3
				},
			}])).encode("utf-8")
		raw=payload(u_shape)
		with self.assertRaisesRegex(ValueError,"außerhalb der WFS-BBOX"):
			validate_layer(raw,"achsen",bounds,max_features=4000)
		_,view,summary=validated_wfs(raw,"achsen",bounds,
			max_features=4000)
		self.assertEqual(summary["anzahl"],1)
		self.assertEqual(summary["wfs_bbox_nur_huelle_anzahl"],1)
		self.assertEqual(summary["wfs_bbox_nur_huelle_gip_ids"],["777"])
		self.assertTrue(view["features"][0]["properties"]["wfs_bbox_nur_huelle"])
		self.assertEqual(view["features"][0]["properties"]["gip_objectid"],"777")
		# Nur eine entfernte Linie mit nicht überlappender Hülle
		# MUSS weiterhin als fehlerhafte WFS-Antwort gelten.
		far=payload([(x+10000,y) for x,y in u_shape])
		with self.assertRaisesRegex(ValueError,
			"GIP_OBJECTID=777.*Hüllrechteck-Treffer=False"):
			validated_wfs(far,"achsen",bounds,max_features=4000)

	def test_wfs_numeric_bbox_rounding_is_bounded_logged_and_no_geometry_edit(self):
		# Alsergrund-WFS: real gemessener Randabstand 0,059 m
		# in EPSG:3857 bei GIP_OBJECTID=20028505.
		# Die Hülle des zweipunktigen Linienobjekts berührt
		# die Anfrage genauso wenig wie die Linie selbst.
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
				"type":"Feature","id":"WFS.20028505",
				"geometry":geom,
				"properties":{
					"GIP_OBJECTID":20028505,
					"NODEFROM_OBJECTID":11,
					"NODETO_OBJECTID":12,
					"FOW":3,
				},
			}])).encode("utf-8")
		near=sample("achsen",0.059)
		with self.assertRaisesRegex(ValueError,"außerhalb der WFS-BBOX"):
			validate_layer(near,"achsen",bounds,max_features=4000)
		_,view,summary=validated_wfs(near,"achsen",bounds,
			max_features=4000)
		self.assertEqual(summary["wfs_bbox_numerische_randtreffer_anzahl"],1)
		self.assertEqual(
			summary["wfs_bbox_numerische_randtreffer"][0]["gip_id"],
			"20028505")
		self.assertAlmostEqual(
			summary["wfs_bbox_numerische_randtreffer"][0]
				["abstand_epsg3857_m"],0.059,delta=.0001)
		self.assertFalse(view["features"][0]["properties"]["wfs_bbox_nur_huelle"])
		self.assertAlmostEqual(
			view["features"][0]["properties"]["wfs_bbox_numerischer_randabstand_m"],
			0.059,delta=.0001)
		# Das ursprüngliche Quell-GIS-Polygon/LineString
		# darf NICHT gepuffert oder in die BBOX hinein verschoben werden.
		self.assertEqual(view["features"][0]["geometry"],
			json.loads(near)["features"][0]["geometry"])
		for distance in (.251,1.,10.,100.):
			with self.subTest(distance=distance):
				with self.assertRaisesRegex(ValueError,"Toleranz=0.250"):
					validated_wfs(sample("achsen",distance),
						"achsen",bounds,max_features=4000)
		# Punktknoten bekommen keine Achsen-Toleranz.
		with self.assertRaisesRegex(ValueError,"außerhalb der WFS-BBOX"):
			validated_wfs(sample("knoten",0.059),"knoten",bounds,
				max_features=4000)
		# Auch im Legacy-Validator kann niemals eine ungeprüfte
		# größere Toleranz eingeschaltet werden.
		with self.assertRaisesRegex(ValueError,"0,25 m"):
			validate_layer(near,"achsen",bounds,max_features=4000,
				bbox_numeric_tolerance_m=1.)

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
			"crs":"EPSG:31256","nachweislich_ohne_strassenraum":True},
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
				"crs":"EPSG:31256","tile_id":tile["id"]})
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
