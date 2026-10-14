"""Wienweiter GIP-WFS-Cache und zentraler, deduplizierter SQLite-Graph.

Kein gesamter WFS-Abruf, keine WFS-Daten ungeprüft zusammenkleben:
pro AOI-Kachel mit Halo abfragen, Limits hart prüfen, Original-ID
in SQLite zentral deduplizieren und Stützpunkte metrisch indizieren.

Achtung: kein Kataster-/FMZK-Downloader; das folgt getrennten Providern.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3

from pyproj import Transformer
from shapely.geometry import box, shape
from shapely.ops import transform
from shapely.wkb import dumps, loads

from scripts.assign_gip_section_areas import prepare_graph
from scripts.fetch_gip_sections import (
	LAYERS, build_wfs_url, validate_layer, _download,
)
from scripts.geojson_crs import require_geojson_lonlat
from scripts.wienwide_grid import read_manifest, checksum

TO_MERCATOR = Transformer.from_crs("EPSG:31256", "EPSG:3857",
	always_xy=True).transform
AXES = "abschnitte_achsen.geojson"
NODES = "abschnitte_knoten.geojson"
REPORT = "wien_gip_bericht.json"
SCHEMA = 1


def urls_for_tile(tile, halo, max_features):
	x0,y0,x1,y1 = tile["bounds_31256"]
	area = transform(TO_MERCATOR, box(x0-halo,y0-halo,x1+halo,y1+halo).segmentize(10))
	bounds = area.bounds
	return {kind: build_wfs_url(layer, bounds, max_features=max_features)
		for kind, layer in LAYERS.items()}, bounds


def _read_features(path):
	doc = json.loads(Path(path).read_text(encoding="utf-8"))
	if doc.get("type") != "FeatureCollection" or not isinstance(doc.get("features"), list):
		raise ValueError(f"GIP-Cache keine GeoJSON FeatureCollection: {path}")
	return doc["features"]


def validated_wfs(raw, kind, bounds, *, max_features):
	"""Leere WFS-Antwort als echte Nullmenge, nicht als Transportfehler.

	Die Testgebietsfunktion verlangt absichtlich >0 Features;
	hier sind leere, korrekt deklarierte Kacheln (z.B. Gewässer)
	im landesweiten Lauf zulässig. Unbekanntes CRS oder eine
	vom Server gemeldete höhere Anzahl bleibt ein Fehler.
	"""
	try:
		return validate_layer(raw,kind,bounds,max_features=max_features)
	except ValueError as exc:
		if "keine GIP-Features" not in str(exc):
			raise
		try:
			doc=json.loads(raw.decode("utf-8-sig"))
		except (UnicodeError,json.JSONDecodeError) as cause:
			raise ValueError("Leere WFS-Antwort ist kein GeoJSON") from cause
		if doc.get("type")!="FeatureCollection" or doc.get("features")!=[]:
			raise
		require_geojson_lonlat(doc,label=f"GIP {kind}")
		for key in ("totalFeatures","numberMatched"):
			value=doc.get(key)
			if value is not None and value!="unknown":
				try:
					count=int(value)
				except (ValueError,TypeError) as cause:
					raise ValueError(f"Ungültige Anzahl {key}") from cause
				if count!=0:
					raise ValueError(f"WFS meldet {key}={count} trotz leerer Kachel")
		return doc,{"type":"FeatureCollection","features":[]},{
			"anzahl":0,"doppelte_gip_ids":{},
			"quelle_sha256":__import__("hashlib").sha256(raw).hexdigest(),
			"status":"verifizierte_leere_wfs_kachel"}


def fetch_all(manifest_path, root, *, max_features=4000,
	downloader=None, limit_tiles=None):
	"""Kein stiller Teilimport: vollständiges Manifest erforderlich fürs Indexing.

	limit_tiles ist ausschließlich für erste Quellenprobe, der fertige
	Index verlangt zwingend sämtliche Manifest-Kacheln.
	"""
	manifest, _ = read_manifest(manifest_path)
	root = Path(root)
	tiles = manifest["tiles"]
	if limit_tiles is not None:
		if not isinstance(limit_tiles,int) or limit_tiles <= 0:
			raise ValueError("limit_tiles muss positiv sein")
		tiles = tiles[:limit_tiles]
	fetch = downloader or _download
	results = []
	for i,tile in enumerate(tiles, 1):
		dest = root/tile["id"]
		urls, bounds = urls_for_tile(tile, manifest["halo_m"], max_features)
		targets = {kind:dest/(AXES if kind == "achsen" else NODES)
			for kind in LAYERS}
		meta = dest/REPORT
		if meta.is_file():
			doc = json.loads(meta.read_text(encoding="utf-8"))
			if doc.get("urls") != urls or doc.get("tile_id") != tile["id"]:
				raise ValueError(f"{tile['id']}: Cache zu anderer Anfrage")
			for kind, path in targets.items():
				if not path.is_file() or checksum(path) != doc["sha256"].get(kind):
					raise ValueError(f"{tile['id']}: GIP-Cache unvollständig/verändert")
			results.append({"tile":tile["id"],"cache":True})
			continue
		if any(p.exists() for p in targets.values()):
			raise ValueError(f"{tile['id']}: Teilcache ohne Abschlussbericht; prüfen")
		# Erst BEIDE Quellen vollständig validieren, dann schreiben.
		views = {}
		summary = {}
		for kind in LAYERS:
			raw = fetch(urls[kind])
			_, view, stats = validated_wfs(raw, kind, bounds,
				max_features=max_features)
			views[kind] = view
			summary[kind] = stats
		dest.mkdir(parents=True, exist_ok=True)
		for kind,path in targets.items():
			tmp = path.with_suffix(path.suffix+".tmp")
			tmp.write_text(json.dumps(views[kind],ensure_ascii=False)+"\n",
				encoding="utf-8")
			tmp.replace(path)
		report = {
			"schema_version": SCHEMA, "created_utc":datetime.now(timezone.utc).isoformat(),
			"tile_id":tile["id"], "urls":urls,
			"max_features":max_features,
			"bbox_3857":list(bounds),
			"sha256":{kind:checksum(path) for kind,path in targets.items()},
			"quelle_sha256":{kind:summary[kind]["quelle_sha256"] for kind in LAYERS},
			"anzahl":{kind:summary[kind]["anzahl"] for kind in LAYERS},
		}
		tmp=meta.with_suffix(".json.tmp")
		tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
		tmp.replace(meta)
		results.append({"tile":tile["id"],"cache":False})
		print(f"GIP {i}/{len(tiles)} {tile['id']}: "
			f"{report['anzahl']['achsen']} Achsen, {report['anzahl']['knoten']} Knoten")
	return results


def connect(path, *, readonly=True):
	if readonly:
		if not Path(path).is_file():
			raise FileNotFoundError(f"GIP-Katalog fehlt: {path}")
		from urllib.parse import quote
		connection = sqlite3.connect("file:"+quote(str(Path(path).resolve()),safe="/")+"?mode=ro",uri=True)
	else:
		connection = sqlite3.connect(path)
	connection.row_factory=sqlite3.Row
	return connection


def build_index(manifest_path, root, output):
	"""Zentrale Quelle aller GIP-IDs und Voronoi-Sites mit SQLite-RTree.

	Bestehenden Index niemals überschreiben; fehlende Kachel stoppen.
	"""
	manifest,aoi=read_manifest(manifest_path)
	root,output=Path(root),Path(output)
	if output.exists():
		raise FileExistsError(f"GIP-Index existiert: {output}")
	output.parent.mkdir(parents=True, exist_ok=True)
	temp=output.with_suffix(output.suffix+".tmp")
	if temp.exists():
		raise FileExistsError(f"Vorheriger temporärer Index existiert: {temp}")
	digests=[]
	for tile in manifest["tiles"]:
		folder=root/tile["id"]
		report_path=folder/REPORT
		if not report_path.is_file():
			raise FileNotFoundError(f"GIP-Kachel fehlt: {tile['id']} ({report_path})")
		report=json.loads(report_path.read_text(encoding="utf-8"))
		if report.get("tile_id")!=tile["id"] or report.get("schema_version")!=SCHEMA:
			raise ValueError(f"GIP-Kachelbericht inkonsistent: {tile['id']}")
		feature_limit=report.get("max_features",4000)
		if not isinstance(feature_limit,int) or not 100<=feature_limit<=10000:
			raise ValueError(f"{tile['id']}: ungültiges GIP-WFS-Limit")
		urls,_=urls_for_tile(tile,manifest["halo_m"],feature_limit)
		if report.get("urls") != urls:
			raise ValueError(f"{tile['id']}: GIP-Cachingparameter/Anfrage nicht wie erwartet")
		for kind,name in (("achsen",AXES),("knoten",NODES)):
			p=folder/name
			if checksum(p)!=report["sha256"][kind]:
				raise ValueError(f"{tile['id']}: Quelle nach Download verändert")
		digests.append({"tile":tile["id"],"achsen":report["sha256"]["achsen"],
			"knoten":report["sha256"]["knoten"]})
	# Kein Import der Rohdaten, sondern lokale geprüfte Kartenansichten.
	try:
		with connect(temp,readonly=False) as db:
			db.executescript("""
				PRAGMA journal_mode=DELETE;
				CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
				CREATE TABLE axes(
					pk INTEGER PRIMARY KEY, gip TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
					fow INTEGER, node_from TEXT NOT NULL,node_to TEXT NOT NULL,
					wkb BLOB NOT NULL);
				CREATE TABLE nodes(
					pk INTEGER PRIMARY KEY, gip TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
					x REAL NOT NULL,y REAL NOT NULL,wkb BLOB NOT NULL);
				CREATE VIRTUAL TABLE node_spatial USING rtree(pk,minx,maxx,miny,maxy);
				CREATE TABLE sites(
					pk INTEGER PRIMARY KEY, axis_pk INTEGER NOT NULL,
					x REAL NOT NULL,y REAL NOT NULL);
				CREATE VIRTUAL TABLE site_spatial USING rtree(pk,minx,maxx,miny,maxy);
				CREATE INDEX sites_by_axis ON sites(axis_pk);
				CREATE TABLE node_degrees(gip TEXT PRIMARY KEY,degree INTEGER NOT NULL);
			""")
			duplicates=Counter()
			for tile in manifest["tiles"]:
				folder=root/tile["id"]
				features_a=_read_features(folder/AXES)
				features_n=_read_features(folder/NODES)
				axes,nodes=prepare_graph(features_a,features_n)
				for item in axes:
					old=db.execute("SELECT pk,name,fow,node_from,node_to,wkb FROM axes WHERE gip=?",
						(item["id"],)).fetchone()
					if old:
						if (old["name"]!=item["name"] or old["fow"]!=item["fow"]
							or old["node_from"]!=item["start"] or old["node_to"]!=item["end"]
							or not loads(old["wkb"]).equals_exact(item["geometry"],0)):
							raise ValueError(f"Konflikt für GIP-Achse {item['id']} über Kachelgrenze")
						duplicates["achsen"]+=1
						continue
					db.execute("INSERT INTO axes(gip,name,fow,node_from,node_to,wkb) VALUES (?,?,?,?,?,?)",
						(item["id"],item["name"],item["fow"],item["start"],
						 item["end"],dumps(item["geometry"])))
				for item in nodes:
					old=db.execute("SELECT pk,name,wkb FROM nodes WHERE gip=?",
						(item["id"],)).fetchone()
					if old:
						if (old["name"]!=item["name"] or
							not loads(old["wkb"]).equals_exact(item["geometry"],0)):
							raise ValueError(f"Konflikt für GIP-Knoten {item['id']} über Kachelgrenze")
						duplicates["knoten"]+=1
						continue
					geom=item["geometry"]; x,y=geom.x,geom.y
					cur=db.execute("INSERT INTO nodes(gip,name,x,y,wkb) VALUES (?,?,?,?,?)",
						(item["id"],item["name"],x,y,dumps(geom)))
					db.execute("INSERT INTO node_spatial VALUES (?,?,?,?,?)",
						(cur.lastrowid,x,x,y,y))
			db.execute("""
				INSERT INTO node_degrees(gip,degree)
				SELECT nid,COUNT(*) FROM (
					SELECT node_from AS nid FROM axes
					UNION ALL SELECT node_to AS nid FROM axes
				) GROUP BY nid
			""")
			# Auf den kompletten Satz aller Achsen referenzierende Knoten
			# im AOI-Inneren müssen verfügbar sein (WFS-Rand darf extern fehlen).
			for row in db.execute("SELECT gip,node_from,node_to,wkb FROM axes"):
				geom=loads(row["wkb"])
				for nid,point in ((row["node_from"],geom.coords[0]),
						(row["node_to"],geom.coords[-1])):
					# Innerhalb von 7 m zum AOI: Knoten für 7-m-Kreise nötig.
					from shapely.geometry import Point
					if aoi.buffer(7).covers(Point(point)):
						if not db.execute("SELECT 1 FROM nodes WHERE gip=?",(nid,)).fetchone():
							raise ValueError(f"GIP-Referenzknoten {nid} bei Achse {row['gip']} "
								"nahe AOI fehlt")
			site_count=0
			seen_sites={}
			# Alle Quellachsen in global identischem 5-m-Abtastschema;
			# keine kachelabhängigen Stützpunkte erzeugen.
			region=aoi.envelope.buffer(manifest["halo_m"]+30)
			for row in db.execute("SELECT pk,gip,wkb FROM axes"):
				line=loads(row["wkb"])
				n=max(1,math.ceil(line.length/5))
				for i in range(n):
					point=line.interpolate((i+.5)/n,normalized=True)
					if not region.covers(point):
						continue
					key=(round(point.x,3),round(point.y,3))
					if key in seen_sites:
						raise ValueError(f"Doppelte GIP-Stützpunkte (1 mm) "
							f"bei {row['gip']} und {seen_sites[key]}")
					seen_sites[key]=row["gip"]
					cur=db.execute("INSERT INTO sites(axis_pk,x,y) VALUES (?,?,?)",
						(row["pk"],point.x,point.y))
					db.execute("INSERT INTO site_spatial VALUES (?,?,?,?,?)",
						(cur.lastrowid,point.x,point.x,point.y,point.y))
					site_count+=1
			if site_count==0:
				raise ValueError("GIP-AOI liefert keine einzige Voronoi-Stützstelle; "
					"Quellen und Bezugsgebiet prüfen")
			stats={
				"schema_version":SCHEMA,"manifest_sha256":checksum(manifest_path),
				"tile_count":len(manifest["tiles"]),"fragment_hashes":digests,
				"achsen":db.execute("SELECT COUNT(*) FROM axes").fetchone()[0],
				"knoten":db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
				"voronoi_sites":site_count,
				"duplikate_zusammengefuehrt":dict(duplicates),
				"sampling_m":5,"knotenradius_m":7,"max_axis_distance_m":25,
				"status":"Vollständiger Cache der im AOI-Raster angefragten GIP-WFS-Kacheln; "
					"noch keine Aussage über amtliche Graphvollständigkeit",
			}
			for key,value in stats.items():
				db.execute("INSERT INTO meta VALUES (?,?)",
					(key,json.dumps(value,ensure_ascii=False)))
			db.commit()
		temp.replace(output)
	except BaseException:
		temp.unlink(missing_ok=True)
		raise
	return stats


def main():
	p=argparse.ArgumentParser(description=__doc__)
	sub=p.add_subparsers(dest="action",required=True)
	f=sub.add_parser("fetch")
	f.add_argument("--manifest",type=Path,required=True)
	f.add_argument("--out-dir",type=Path,required=True)
	f.add_argument("--limit-tiles",type=int,help="Nur Datenprobe, KEINE komplette Quelle")
	f.add_argument("--max-features",type=int,default=4000)
	b=sub.add_parser("index")
	b.add_argument("--manifest",type=Path,required=True)
	b.add_argument("--fragments",type=Path,required=True)
	b.add_argument("--out",type=Path,required=True)
	args=p.parse_args()
	try:
		if args.action=="fetch":
			result=fetch_all(args.manifest,args.out_dir,max_features=args.max_features,
				limit_tiles=args.limit_tiles)
		else:
			result=build_index(args.manifest,args.fragments,args.out)
		print(json.dumps({"result":result if args.action=="index"
			else {"tiles":len(result),"complete":args.limit_tiles is None}},
			ensure_ascii=False,indent=2))
	except (OSError,ValueError,TypeError,KeyError,sqlite3.Error) as e:
		p.exit(1,f"Fehler: {e}\n")


if __name__=="__main__":
	main()
