"""Exportiert geprüfte Wien-V0-Straßenflächen direkt als GeoPackage EPSG:31256.

Vier räumliche Layer: gip_abschnitte, knotenbereiche, sonderachsen,
nicht_zugeordnet. Keine Neuklassifikation, keine GeoJSON-/WGS84-
Transformation und kein Dissolve über originale Tile-/GIP-IDs.
Die V0-Sonderachsen enthalten bereits keine Einzel-GIP-Zuordnung:
sie bleiben ausdrücklich kachelweise Sammelflächen.

Nur vollständige, zur AOI und sämtlichen Eingabe-SHA passende
Partitionen exportieren. SQLite-GeoPackage inkl. räumlichem RTree
direkt erzeugen, ohne zusätzliche GIS-Paket-Abhängigkeiten.
"""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
import struct
from urllib.parse import quote

from pyproj import CRS
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.wkb import dumps, loads

from scripts.wienwide_grid import checksum, read_manifest
from scripts.wienwide_partition import SCHEMA as PARTITION_SCHEMA, report_results

LAYERS = ("gip_abschnitte", "knotenbereiche", "sonderachsen", "nicht_zugeordnet")
SOURCE_GROUP = {"knotenbereich": "knotenbereiche",
	"sonderachse": "sonderachsen", "nicht_zugeordnet": "nicht_zugeordnet"}
EPSG = 31256
SCHEMA = 1


def readonly(path):
	p=Path(path)
	if not p.is_file():
		raise FileNotFoundError(f"Eingabedaten fehlen: {p}")
	return sqlite3.connect("file:"+quote(str(p.resolve()),safe="/")+"?mode=ro",uri=True)


def gpkg_blob(geometry):
	"""GPKGBinary: Magic, Version=0, LittleEndian + XY-Envelope, EPSG:31256."""
	if (geometry.is_empty or not geometry.is_valid or geometry.area<=0
		or geometry.geom_type not in ("Polygon","MultiPolygon")):
		raise ValueError("Keine gültige polygonale QA-Geometrie")
	geom=MultiPolygon([geometry]) if isinstance(geometry,Polygon) else geometry
	bounds=geom.bounds
	if any(not math.isfinite(v) for v in bounds):
		raise ValueError("Nicht-endliche Polygon-Bounds")
	return (b"GP\x00\x03"+struct.pack("<i",EPSG)+
		struct.pack("<4d",bounds[0],bounds[2],bounds[1],bounds[3])+
		dumps(geom,hex=False,big_endian=False,output_dimension=2))


def init_gpkg(db):
	db.executescript("""
		PRAGMA application_id=1196444487;
		PRAGMA user_version=10200;
		PRAGMA foreign_keys=ON;
		CREATE TABLE gpkg_spatial_ref_sys(
			srs_name TEXT NOT NULL,srs_id INTEGER NOT NULL PRIMARY KEY,
			organization TEXT NOT NULL,organization_coordsys_id INTEGER NOT NULL,
			definition TEXT NOT NULL,description TEXT);
		CREATE TABLE gpkg_contents(
			table_name TEXT NOT NULL PRIMARY KEY,data_type TEXT NOT NULL,
			identifier TEXT UNIQUE,description TEXT DEFAULT '',
			last_change DATETIME NOT NULL DEFAULT
				(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
			min_x DOUBLE,min_y DOUBLE,max_x DOUBLE,max_y DOUBLE,
			srs_id INTEGER REFERENCES gpkg_spatial_ref_sys(srs_id));
		CREATE TABLE gpkg_geometry_columns(
			table_name TEXT NOT NULL,column_name TEXT NOT NULL,
			geometry_type_name TEXT NOT NULL,srs_id INTEGER NOT NULL,
			z TINYINT NOT NULL,m TINYINT NOT NULL,
			PRIMARY KEY(table_name,column_name),
			UNIQUE(table_name),
			FOREIGN KEY (table_name) REFERENCES gpkg_contents(table_name),
			FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id));
		CREATE TABLE gpkg_extensions(
			table_name TEXT,column_name TEXT,extension_name TEXT NOT NULL,
			definition TEXT NOT NULL,scope TEXT NOT NULL,
			UNIQUE(table_name,column_name,extension_name));
		CREATE TABLE qa_provenienz(
			"key" TEXT NOT NULL PRIMARY KEY,
			"value" TEXT NOT NULL);
	""")
	srs=CRS.from_epsg(EPSG)
	db.executemany("INSERT INTO gpkg_spatial_ref_sys VALUES (?,?,?,?,?,?)",[
		("Undefined Cartesian SRS",-1,"NONE",-1,"undefined",""),
		("Undefined geographic SRS",0,"NONE",0,"undefined",""),
		(srs.name,EPSG,"EPSG",EPSG,srs.to_wkt(version="WKT1_GDAL"),"")])
	for layer in LAYERS:
		db.execute(f"""CREATE TABLE "{layer}"(
			fid INTEGER PRIMARY KEY AUTOINCREMENT,
			geom MULTIPOLYGON NOT NULL,
			kachel_id TEXT NOT NULL,
			kategorie TEXT NOT NULL,
			gip_id TEXT,
			strassenname TEXT,
			fow INTEGER,
			knoten_von TEXT,
			knoten_nach TEXT,
			flaeche_m2 REAL NOT NULL,
			gip_gesamt_m2 REAL)""")
		description={
			"gip_abschnitte":"GIP-Voronoi-Abschnittsflaechen je Kachel und GIP-ID (FOW gemaess Partition)",
			"knotenbereiche":"Gesonderte Knoten-/Kreuzungsflaechen je Kachel aggregiert",
			"sonderachsen":"V0: Nicht-FOW3-Sammelflaechen; bei V2 mit allen FOW-Klassen leer",
			"nicht_zugeordnet":"Verbleibende nicht zugeordnete Strassenraumflaechen"
		}[layer]
		db.execute("""INSERT INTO gpkg_contents
			(table_name,data_type,identifier,description,srs_id)
			VALUES (?,'features',?,?,?)""",(layer,layer,description,EPSG))
		db.execute("""INSERT INTO gpkg_geometry_columns
			VALUES (?,'geom','MULTIPOLYGON',?,0,0)""",(layer,EPSG))
		db.execute(f'''CREATE VIRTUAL TABLE "rtree_{layer}_geom"
			USING rtree(id,minx,maxx,miny,maxy)''')
	db.execute("""INSERT INTO gpkg_contents
		(table_name,data_type,identifier,description)
		VALUES ('qa_provenienz','attributes','qa_provenienz',
			'Quelle, Pruefsummen und Exportbilanz als JSON-Werte')""")


def finish_layer(db,layer,bounds):
	"""Vollständige GPKG-RTree-Erweiterung einschließlich Änderungs-Trigger."""
	if bounds is not None:
		x0,y0,x1,y1=bounds
		db.execute("""UPDATE gpkg_contents
			SET min_x=?,min_y=?,max_x=?,max_y=?
			WHERE table_name=?""",(x0,y0,x1,y1,layer))
	db.execute("""INSERT INTO gpkg_extensions
		VALUES (?,'geom','gpkg_rtree_index',
		'http://www.geopackage.org/spec120/#extension_rtree','write-only')""",
		(layer,))
	t=f'"{layer}"'
	r=f'"rtree_{layer}_geom"'
	# Die Trigger werden nach dem initialen Füllen erzeugt. GDAL/QGIS
	# registrieren ST_MinX/ST_IsEmpty beim anschließenden Editieren.
	commands=[
		("insert",f"""AFTER INSERT ON {t}
			WHEN (NEW.geom NOT NULL AND NOT ST_IsEmpty(NEW.geom))
			BEGIN INSERT OR REPLACE INTO {r}
			VALUES (NEW.fid,ST_MinX(NEW.geom),ST_MaxX(NEW.geom),
				ST_MinY(NEW.geom),ST_MaxY(NEW.geom)); END"""),
		("delete",f"""AFTER DELETE ON {t} WHEN OLD.geom NOT NULL
			BEGIN DELETE FROM {r} WHERE id=OLD.fid; END"""),
		("update1",f"""AFTER UPDATE OF geom ON {t}
			WHEN OLD.fid=NEW.fid
				AND NEW.geom NOT NULL AND NOT ST_IsEmpty(NEW.geom)
			BEGIN INSERT OR REPLACE INTO {r}
			VALUES (NEW.fid,ST_MinX(NEW.geom),ST_MaxX(NEW.geom),
				ST_MinY(NEW.geom),ST_MaxY(NEW.geom)); END"""),
		("update2",f"""AFTER UPDATE OF geom ON {t}
			WHEN OLD.fid=NEW.fid
				AND (NEW.geom IS NULL OR ST_IsEmpty(NEW.geom))
			BEGIN DELETE FROM {r} WHERE id=OLD.fid; END"""),
		("update3",f"""AFTER UPDATE ON {t}
			WHEN OLD.fid!=NEW.fid
				AND NEW.geom NOT NULL AND NOT ST_IsEmpty(NEW.geom)
			BEGIN DELETE FROM {r} WHERE id=OLD.fid;
			INSERT OR REPLACE INTO {r}
			VALUES (NEW.fid,ST_MinX(NEW.geom),ST_MaxX(NEW.geom),
				ST_MinY(NEW.geom),ST_MaxY(NEW.geom)); END"""),
		("update4",f"""AFTER UPDATE ON {t}
			WHEN OLD.fid!=NEW.fid
				AND (NEW.geom IS NULL OR ST_IsEmpty(NEW.geom))
			BEGIN DELETE FROM {r} WHERE id IN (OLD.fid,NEW.fid); END""")
	]
	for name,body in commands:
		db.execute(f'CREATE TRIGGER "rtree_{layer}_geom_{name}" {body}')


def export(manifest_path,gip_path,street_root,partition_path,output):
	manifest,aoi=read_manifest(manifest_path)
	gip_path,partition_path=Path(gip_path),Path(partition_path)
	street_root,output=Path(street_root),Path(output)
	if output.exists():
		raise FileExistsError(f"QA-GeoPackage existiert bereits: {output}")
	tmp=output.with_suffix(output.suffix+".tmp")
	if tmp.exists():
		raise FileExistsError(f"Vorheriger temporärer Export existiert: {tmp}")
	tile_map={tile["id"]:tile for tile in manifest["tiles"]}
	expected={"manifest_sha256":checksum(manifest_path),
		"gip_sha256":checksum(gip_path),
		"schema_version":str(PARTITION_SCHEMA)}
	with closing(readonly(partition_path)) as src, closing(readonly(gip_path)) as gip:
		src.row_factory=sqlite3.Row
		gip.row_factory=sqlite3.Row
		actual=dict(src.execute("SELECT key,value FROM config"))
		actual.pop("querschnitt_regel",None)
		if actual!=expected and actual!={**expected,"junction_policy":"none"} and actual!={**expected,"junction_policy":"none","fow_policy":"all"} and actual!={**expected,"junction_policy":"gip2-turn-use-convex-hull","fow_policy":"all"} and actual!={**expected,"junction_policy":"voronoi-stable-width-v1","fow_policy":"all"}:
			raise ValueError("Partition gehört zu anderem Manifest/GIP-Index")
		gip_meta={row["key"]:json.loads(row["value"])
			for row in gip.execute("SELECT key,value FROM meta")}
		if gip_meta.get("manifest_sha256")!=expected["manifest_sha256"]:
			raise ValueError("GIP-Index gehört nicht zum Manifest")
		balance=report_results(src,manifest)
		street_checks={}
		tile_areas={}
		for row in src.execute("SELECT id,street_sha256,area,assigned,unresolved,stats_json FROM tiles"):
			tid=row["id"]
			if tid not in tile_map:
				raise ValueError(f"Unbekannte Ergebnis-Kachel {tid}")
			street=street_root/tid/"street.sqlite"
			street_sha=checksum(street)
			from scripts.wienwide_street import load_street_tile
			core=box(*tile_map[tid]["bounds_31256"]).intersection(aoi)
			load_street_tile(street,core)  # prüft auch die FMZK-Regelversion
			if street_sha!=row["street_sha256"]:
				raise ValueError(f"{tid}: Straßenraum-Quelldatei verändert")
			street_checks[tid]=street_sha
			stats=json.loads(row["stats_json"])
			tol=max(.05,row["area"]*1e-6)
			if any(abs(stats.get(key,float("inf")))>tol for key in (
				"fehlend_m2","overlap_m2","ausserhalb_m2")):
				raise ValueError(f"{tid}: ursprüngliche Topologie-QA fehlerhaft")
			tile_areas[tid]=(row["area"],row["assigned"],row["unresolved"])
		if len(tile_areas)!=len(tile_map):
			raise ValueError("Partition enthält nicht alle Bezirkskacheln")
		gip_totals={row["gip_id"]:row["total"] for row in src.execute(
			"""SELECT gip_id,SUM(area) AS total FROM parts
			   WHERE kind='abschnitt' GROUP BY gip_id""")}
		axes={row["gip"]:(row["name"],row["fow"],row["node_from"],row["node_to"])
			for row in gip.execute("SELECT gip,name,fow,node_from,node_to FROM axes")}
		counts=Counter()
		areas=Counter()
		per_tile=defaultdict(lambda:Counter())
		limits={name:None for name in LAYERS}
		output.parent.mkdir(parents=True,exist_ok=True)
		try:
			with closing(sqlite3.connect(tmp)) as target, target:
				init_gpkg(target)
				grouping = gip.execute("SELECT name FROM sqlite_master WHERE "
					"name='merged_members'").fetchone() is not None
				if grouping:
					target.execute("""CREATE TABLE gip_original_zuordnung(
						original_id TEXT PRIMARY KEY,
						representative_id TEXT NOT NULL,
						role TEXT NOT NULL,
						original_fow INTEGER,
						original_name TEXT NOT NULL)""")
					target.execute("""INSERT INTO gpkg_contents(
						table_name,data_type,identifier,description)
						VALUES ('gip_original_zuordnung','attributes',
						'gip_original_zuordnung',
						'Original-GIP-ID zu vereinheitlichtem Strassenabschnitt')""")
					target.executemany(
						"INSERT INTO gip_original_zuordnung VALUES (?,?,?,?,?)",
						gip.execute("SELECT original_id,representative_id,role,"
							"original_fow,original_name FROM merged_members "
							"ORDER BY original_id"))
					missing=target.execute("""SELECT COUNT(*) FROM gip_original_zuordnung m
						LEFT JOIN (SELECT representative_id FROM gip_original_zuordnung
							GROUP BY representative_id) r
						ON m.representative_id=r.representative_id
						WHERE r.representative_id IS NULL""").fetchone()[0]
					if missing:
						raise ValueError("Unaufgelöste Original-GIP-IDs im QA-GPKG")
				for row in src.execute("""SELECT tile_id,kind,gip_id,area,geom
					FROM parts ORDER BY tile_id,kind,gip_id"""):
					tid,kind,gid,stored_area=row["tile_id"],row["kind"],row["gip_id"],row["area"]
					if tid not in tile_map:
						raise ValueError(f"Teilfläche mit unbekannter Kachel {tid}")
					if kind=="abschnitt":
						layer="gip_abschnitte"
						attrs=axes.get(gid)
						if attrs is None or (actual.get("fow_policy") != "all" and attrs[1] != 3):
							raise ValueError(f"Abschnitt {gid}: GIP-ID fehlt oder FOW gemäß Partitionsregel unzulässig")
						name,fow,node_from,node_to=attrs
						total=gip_totals[gid]
					elif kind=="ungeklaert" and gid in SOURCE_GROUP:
						layer=SOURCE_GROUP[gid]
						name=fow=node_from=node_to=total=None
					else:
						raise ValueError(f"Unbekannte QA-Gruppe: {kind}/{gid}")
					geom=loads(row["geom"])
					if (geom.is_empty or geom.geom_type not in ("Polygon","MultiPolygon")
						or not geom.is_valid or geom.area<=0):
						raise ValueError(f"{tid}/{gid}: ungültige Quellgeometrie")
					if abs(geom.area-stored_area)>max(.01,stored_area*1e-8):
						raise ValueError(f"{tid}/{gid}: WKB-Fläche weicht vom SQLite-Wert ab")
					core=box(*tile_map[tid]["bounds_31256"]).intersection(aoi)
					if geom.difference(core).area>.01:
						raise ValueError(f"{tid}/{gid}: Polygon reicht über den Kachelkern")
					blob=gpkg_blob(geom)
					cur=target.execute(f"""INSERT INTO "{layer}"
						(geom,kachel_id,kategorie,gip_id,strassenname,fow,
						knoten_von,knoten_nach,flaeche_m2,gip_gesamt_m2)
						VALUES (?,?,?,?,?,?,?,?,?,?)""",
						(blob,tid,"abschnitt" if kind=="abschnitt" else gid,
						 gid if kind=="abschnitt" else None,name,fow,node_from,
						 node_to,stored_area,total))
					x0,y0,x1,y1=geom.bounds
					target.execute(f'''INSERT INTO "rtree_{layer}_geom"
						VALUES (?,?,?,?,?)''',(cur.lastrowid,x0,x1,y0,y1))
					old=limits[layer]
					limits[layer]=(x0,y0,x1,y1) if old is None else (
						min(old[0],x0),min(old[1],y0),
						max(old[2],x1),max(old[3],y1))
					counts[layer]+=1
					areas[layer]+=stored_area
					per_tile[tid]["parts"]+=stored_area
					per_tile[tid]["assigned" if kind=="abschnitt" else "unresolved"]+=stored_area
				for tid,(total,assigned,unresolved) in tile_areas.items():
					got=per_tile[tid]
					tol=max(.05,total*1e-6)
					if any(abs(got[k]-wanted)>tol for k,wanted in (
						("parts",total),("assigned",assigned),
						("unresolved",unresolved))):
						raise ValueError(f"{tid}: Teilflächensummen stimmen nicht")
				for layer in LAYERS:
					finish_layer(target,layer,limits[layer])
				if (abs(areas["gip_abschnitte"]-balance["abschnitte_m2"])>.05
					or abs(sum(areas[layer] for layer in LAYERS[1:])-
						balance["ungeklaert_m2"])>.05):
					raise ValueError("QA-Layersummen weichen von der Partition ab")
				report={
					"schema_version":SCHEMA,
					"erzeugt_utc":datetime.now(timezone.utc).isoformat(),
					"crs":"EPSG:31256",
					"manifest_sha256":expected["manifest_sha256"],
					"gip_sha256":expected["gip_sha256"],
					"partition_sha256":checksum(partition_path),
					"street_sha256":street_checks,
					"kacheln":len(tile_map),
					"layer_anzahl":dict(counts),
					"layer_flaeche_m2":dict(areas),
					"voronoi_bericht":balance,
					"gip_kantenvereinigung": ("parallel-gip-groups-v1"
						if grouping else "keine"),
					"gip_original_zuordnung_anzahl": (
						target.execute("SELECT COUNT(*) FROM gip_original_zuordnung").fetchone()[0]
						if grouping else 0),
					"hinweis":"Sonderachsen und Knotenbereiche wurden von V0 pro "
						"Kachel vereinigt. Sonderachsen können aus dieser "
						"Partition nicht rückwirkend nach GIP-ID/FOW getrennt "
						"werden. Abschnittsflächen bleiben je GIP-ID und Kachel "
						"separat, nicht aufgelöst/dissolved.",
				}
				for key,value in report.items():
					target.execute("INSERT INTO qa_provenienz VALUES (?,?)",
						(key,json.dumps(value,ensure_ascii=False)))
				if target.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
					raise ValueError("SQLite-Integritätsprüfung des QA-GPKG fehlgeschlagen")
			tmp.replace(output)
			return report
		except BaseException:
			tmp.unlink(missing_ok=True)
			raise


def main():
	p=argparse.ArgumentParser(description=__doc__)
	p.add_argument("--manifest",type=Path,required=True)
	p.add_argument("--gip-index",type=Path,required=True)
	p.add_argument("--street-root",type=Path,required=True)
	p.add_argument("--partition-db",type=Path,required=True)
	p.add_argument("--out",type=Path,required=True)
	args=p.parse_args()
	try:
		report=export(args.manifest,args.gip_index,args.street_root,
			args.partition_db,args.out)
		print(json.dumps({"ausgabe":str(args.out),
			"kacheln":report["kacheln"],
			"layer_anzahl":report["layer_anzahl"],
			"layer_flaeche_m2":report["layer_flaeche_m2"],
			"strassenraum_m2":report["voronoi_bericht"]["strassenraum_m2"],
			"bilanzdifferenz_m2":report["voronoi_bericht"]["bilanzdifferenz_m2"]},
			ensure_ascii=False,indent=2))
	except (OSError,ValueError,TypeError,KeyError,sqlite3.Error) as exc:
		p.exit(1,f"Fehler: {exc}\n")


if __name__=="__main__":
	main()
