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
		# Keine auslaufende numerische Randtoleranz: der Server darf
		# Superset-Kandidaten zurückgeben, lokal werden nur echte
		# Geometrieschnitte mit der bereits 75 m gepufferten BBOX
		# behalten. Alle übersprungenen GIP-IDs protokollieren.
		return validate_layer(raw,kind,bounds,max_features=max_features,
			filter_wfs_bbox_superset=True)
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
			"wfs_antwort_features":{kind:summary[kind].get(
				"antwort_features", summary[kind]["anzahl"]) for kind in LAYERS},
			"wfs_bbox_ausgeschlossen": {
				kind:{
					"anzahl":summary[kind].get("wfs_bbox_ausgeschlossen_anzahl",0),
					"gip_ids_mit_abstand":summary[kind].get(
						"wfs_bbox_ausgeschlossen",[]),
				}
				for kind in LAYERS
			},
		}
		tmp=meta.with_suffix(".json.tmp")
		tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
		tmp.replace(meta)
		results.append({"tile":tile["id"],"cache":False})
		print(f"GIP {i}/{len(tiles)} {tile['id']}: "
			f"{report['anzahl']['achsen']} Achsen, {report['anzahl']['knoten']} Knoten"
			f"{', WFS-Kandidaten außerhalb BBOX: '+str(report['wfs_bbox_ausgeschlossen']['achsen']['anzahl']) if report['wfs_bbox_ausgeschlossen']['achsen']['anzahl'] else ''}")
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



# Die kleine GIP-Probe bleibt unverändert streng. Der wienweite Import
# darf nur tatsächlich identische, innerhalb EINER Kachel wiederholte
# WFS-Objekte vor dem vorhandenen prepare_graph zusammenfassen.
# Unterschiedliche Geometrien/Attribute derselben ID bleiben harte Fehler.
_NON_SEMANTIC_VIEW_FIELDS = frozenset((
	"wfs_id", "wfs_bbox_nur_huelle",
	"wfs_bbox_numerischer_randabstand_m", "status",
))


def _source_properties(feature):
	props = feature["properties"]
	return {key: value for key, value in props.items()
		if key not in _NON_SEMANTIC_VIEW_FIELDS}


def _graph_properties(feature, *, kind):
	"""GIP-Graphattribute ohne WFS-Ansichtsmetadaten und Routennummer.

	REG_STRNAME bezeichnet eine Straßenroute (z.B. B12 und B13a).
	Sie kann für genau dieselbe physische GIP-Achse unterschiedlich sein.
	Die Zuordnung beider Quellen bleibt im Index gesondert erhalten.
	"""
	result = _source_properties(feature)
	if kind == "achsen":
		result.pop("reg_strname", None)
	return result


def deduplicate_tile_view(features, *, kind, tile_id, audit=None):
	"""Identische physische Features innerhalb einer Kachel deduplizieren.

	Die einzige erlaubte Abweichung bei Achsen ist REG_STRNAME.
	Geometrie, Topologie und alle übrigen fachlichen Attribute
	müssen exakt übereinstimmen; der lokale Quellcache bleibt unverändert.
	"""
	if kind not in ("achsen", "knoten"):
		raise ValueError(f"Unbekannter GIP-Layertyp: {kind}")
	seen = {}
	unique = []
	duplicates = 0
	for index, feature in enumerate(features):
		props = feature["properties"]
		gid = str(props["gip_objectid"])
		if gid not in seen:
			seen[gid] = (index, feature)
			unique.append(feature)
			continue
		first_index, first = seen[gid]
		first_graph_props = _graph_properties(first, kind=kind)
		current_graph_props = _graph_properties(feature, kind=kind)
		same_attributes = first_graph_props == current_graph_props
		first_geometry = shape(first["geometry"])
		current_geometry = shape(feature["geometry"])
		same_geometry = first_geometry.equals_exact(current_geometry, 0)
		if not (same_attributes and same_geometry):
			mismatching_keys = sorted(
				key for key in set(first_graph_props) | set(current_graph_props)
				if first_graph_props.get(key) != current_graph_props.get(key)
			)
			raise ValueError(
				f"{tile_id}: GIP-{kind}-ID {gid} mehrfach in derselben Kachel "
				f"(Features {first_index}/{index}, "
				f"WFS-IDs {first.get('id')!r}/{feature.get('id')!r}); "
				f"Attribute abweichend: {mismatching_keys}; "
				f"Geometrie identisch: {same_geometry}; "
				"nicht automatisch vereinigen – mit 'diagnose' prüfen"
			)
		duplicates += 1
		if (kind == "achsen" and audit is not None
			and first["properties"].get("reg_strname") != props.get("reg_strname")):
			audit["routenvarianten_in_kachel"] += 1
	return unique, duplicates


def diagnose_id(manifest_path, root, gip_id):
	"""GIP-ID in allen verifizierten Wien-Kachelansichten offline untersuchen."""
	manifest, _aoi = read_manifest(manifest_path)
	root = Path(root)
	occurrences = []
	gip_id = str(gip_id).strip()
	if not gip_id:
		raise ValueError("GIP-ID fehlt")
	for tile in manifest["tiles"]:
		folder = root / tile["id"]
		meta_path = folder / REPORT
		report = json.loads(meta_path.read_text(encoding="utf-8"))
		if report.get("tile_id") != tile["id"]:
			raise ValueError(f"Unpassender GIP-Kachelbericht: {tile['id']}")
		for kind, filename in (("achsen", AXES), ("knoten", NODES)):
			source = folder / filename
			if checksum(source) != report["sha256"][kind]:
				raise ValueError(f"{tile['id']}: GIP-Cache-Hash abweichend")
			for index, feature in enumerate(_read_features(source)):
				props = feature["properties"]
				if str(props.get("gip_objectid")) != gip_id:
					continue
				geom = shape(feature["geometry"])
				occurrences.append({
					"tile_id": tile["id"], "layer": kind,
					"index": index, "wfs_id": feature.get("id"),
					"name": props.get("name"),
					"fow": props.get("fow"),
					"node_from": props.get("node_from"),
					"node_to": props.get("node_to"),
					"bbox_4326": list(geom.bounds),
					"length_degrees": geom.length if kind == "achsen" else None,
					"geometry_wkt": geom.wkt,
					"properties": _source_properties(feature),
				})
	# Die Diagnose darf Varianten sichtbar machen, nicht bereits filtern.
	return {"gip_id": gip_id, "vorkommen": len(occurrences),
		"betroffene_kacheln": sorted({r["tile_id"] for r in occurrences}),
		"fundstellen": occurrences}


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
				-- Amtliche WFS-Feature-IDs und alternative Routenbezeichnungen
				-- nachvollziehbar erhalten; geometrisch nur eine GIP-Achse.
				CREATE TABLE axis_source_variants(
					gip TEXT NOT NULL,
					wfs_id TEXT NOT NULL,
					reg_strname TEXT NOT NULL,
					kachel_vorkommen INTEGER NOT NULL CHECK(kachel_vorkommen >= 1),
					PRIMARY KEY(gip,wfs_id,reg_strname));
			""")
			duplicates=Counter()
			axis_view_reference={}
			for tile in manifest["tiles"]:
				folder=root/tile["id"]
				raw_axes=_read_features(folder/AXES)
				features_n=_read_features(folder/NODES)
				features_a,skipped_a=deduplicate_tile_view(raw_axes,
					kind="achsen",tile_id=tile["id"],audit=duplicates)
				features_n,skipped_n=deduplicate_tile_view(features_n,
					kind="knoten",tile_id=tile["id"])
				duplicates["identische_achsen_in_kachel"]+=skipped_a
				duplicates["identische_knoten_in_kachel"]+=skipped_n
				# Die Quellvarianten über ALLE Kacheln erfassen, auch wenn
				# die physische Achse bereits aus einer anderen Kachel
				# in der zentralen GIP-Tabelle vorhanden ist.
				for feature in raw_axes:
					props=feature["properties"]
					gid=str(props["gip_objectid"])
					source_id=str(feature.get("id") or props.get("wfs_id") or "")
					route=props.get("reg_strname")
					db.execute("""INSERT INTO axis_source_variants
						(gip,wfs_id,reg_strname,kachel_vorkommen)
						VALUES (?,?,?,1)
						ON CONFLICT(gip,wfs_id,reg_strname) DO UPDATE
						SET kachel_vorkommen=kachel_vorkommen+1""",
						(gid,source_id,str(route) if route is not None else ""))
				# Neben Geometrie/Topologie auch alle weiteren technischen
				# Graphattribute über Kachelgrenzen hinweg strikt prüfen.
				# Nur REG_STRNAME darf verschieden sein.
				for feature in features_a:
					gid=str(feature["properties"]["gip_objectid"])
					first=axis_view_reference.get(gid)
					if first is None:
						axis_view_reference[gid]=(tile["id"],feature)
						continue
					first_tile,reference=first
					left=_graph_properties(reference,kind="achsen")
					right=_graph_properties(feature,kind="achsen")
					identical=shape(reference["geometry"]).equals_exact(
						shape(feature["geometry"]),0)
					if left != right or not identical:
						changed=sorted(key for key in set(left)|set(right)
							if left.get(key)!=right.get(key))
						raise ValueError(f"{tile['id']}: GIP-Achse {gid} "
							f"weicht von {first_tile} ab; Attribute: {changed}; "
							f"Geometrie identisch: {identical}")
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
			routes_multiple=db.execute("""SELECT COUNT(*) FROM (
				SELECT gip FROM axis_source_variants
				GROUP BY gip HAVING COUNT(DISTINCT reg_strname)>1)""").fetchone()[0]
			source_variants=db.execute(
				"SELECT COUNT(*) FROM axis_source_variants").fetchone()[0]
			stats={
				"schema_version":SCHEMA,"index_schema_version":2,
				"manifest_sha256":checksum(manifest_path),
				"tile_count":len(manifest["tiles"]),"fragment_hashes":digests,
				"achsen":db.execute("SELECT COUNT(*) FROM axes").fetchone()[0],
				"knoten":db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
				"voronoi_sites":site_count,
				"duplikate_zusammengefuehrt":dict(duplicates),
				"achsen_mit_mehreren_reg_strname":routes_multiple,
				"achsen_quellvarianten":source_variants,
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
	d=sub.add_parser("diagnose",help="Eine GIP-ID in allen lokalen Kacheln prüfen")
	d.add_argument("--manifest",type=Path,required=True)
	d.add_argument("--fragments",type=Path,required=True)
	d.add_argument("--gip-id",required=True)

	args=p.parse_args()
	try:
		if args.action=="fetch":
			result=fetch_all(args.manifest,args.out_dir,max_features=args.max_features,
				limit_tiles=args.limit_tiles)
		elif args.action=="index":
			result=build_index(args.manifest,args.fragments,args.out)
		else:
			result=diagnose_id(args.manifest,args.fragments,args.gip_id)
		print(json.dumps({"result":
			{"tiles":len(result),"complete":args.limit_tiles is None}
			if args.action=="fetch" else result},
			ensure_ascii=False,indent=2))
	except (OSError,ValueError,TypeError,KeyError,sqlite3.Error) as e:
		p.exit(1,f"Fehler: {e}\n")


if __name__=="__main__":
	main()
