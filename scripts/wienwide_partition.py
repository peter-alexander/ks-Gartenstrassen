"""Wienweite GIP-V0-Partition kachelweise, aber mit GIP-GLOBALEN Sites.

Analyse je METERKACHEL, Halo dient nur für die Voronoi-Nachbarschaft.
Knotenradius 7, Stützpunktabstand 5, Achsbuffer 25 und FOW=3 wie V0.
Eingabe: metrisches street-WKB-SQLite je Kachel (siehe wienwide_street).
Ergebnis: SQLite-WKB je (Kachel, GIP-ID), alle ungeklärten Teile
und strenge Flächenbilanz. Kein GeoJSON-Rundweg in Berechnung.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
from time import perf_counter

from shapely import union_all, voronoi_polygons
from shapely.geometry import MultiPoint, box
from shapely.wkb import dumps, loads

from scripts.analyze_gpkg import polygonal_part
from scripts.assign_gip_section_areas import MAX_SITES
from scripts.wienwide_grid import read_manifest, checksum
from scripts.wienwide_gip import connect as connect_gip

SCHEMA = 1
GROUPS = ("knotenbereich","sonderachse","nicht_zugeordnet")


def _polygon(g, label):
	if g is None or g.is_empty or g.area <= 0:
		return None
	poly=polygonal_part(g)
	if poly is None or not poly.is_valid or poly.is_empty:
		raise ValueError(f"{label}: ungültige polygonale Fläche")
	return poly


def _rtree(db, table, bounds):
	x0,y0,x1,y1=bounds
	return db.execute(
		f"SELECT pk FROM {table} WHERE maxx>=? AND minx<=? AND maxy>=? AND miny<=?",
		(x0,x1,y0,y1))


def graph_context(db, bounds, *, halo=75):
	"""Nur benötigte Voronoi-Sites; Knotengrad aus GLOBALEN GIP-Achsen."""
	x0,y0,x1,y1=bounds
	search=(x0-halo,y0-halo,x1+halo,y1+halo)
	site_ids=[r[0] for r in _rtree(db,"site_spatial",search)]
	sites=[]
	axis_ids=set()
	for pk in sorted(site_ids):
		row=db.execute("SELECT axis_pk,x,y FROM sites WHERE pk=?",(pk,)).fetchone()
		sites.append((row["axis_pk"],row["x"],row["y"]))
		axis_ids.add(row["axis_pk"])
	axes={}
	for pk in axis_ids:
		r=db.execute("SELECT pk,gip,name,fow,wkb FROM axes WHERE pk=?",(pk,)).fetchone()
		axes[pk]={"id":r["gip"],"name":r["name"],"fow":r["fow"],
			"geometry":loads(r["wkb"])}
	# Grad ausschließlich aus ALLEN geladenen Achsen, nicht aus
	# den in einer einzelnen Kachel sichtbaren Armen.
	degrees=dict(db.execute("""
		SELECT nid,COUNT(*) AS degree FROM
			(SELECT node_from AS nid FROM axes
			 UNION ALL SELECT node_to AS nid FROM axes)
		GROUP BY nid
	""").fetchall())
	nodes=[]
	node_ids=[r[0] for r in _rtree(db,"node_spatial",
		(x0-7,y0-7,x1+7,y1+7))]
	for pk in node_ids:
		r=db.execute("SELECT gip,wkb FROM nodes WHERE pk=?",(pk,)).fetchone()
		if degrees.get(r["gip"],0)>=3:
			nodes.append(loads(r["wkb"]))
	return sites,axes,nodes


def split_tile(street, core, sites, axes, nodes,
	*, radius=7, max_distance=25):
	"""Identische Semantik zu V0, Voronoi-Sites aus globalem Index.

	Voraussetzung: halo >= max_distance + 5 + 7. Schnitt erfolgt
	im exakt definierten Kern, der pro Kachel disjunkt ist.
	"""
	if (not street.is_valid or not core.is_valid
		or not core.intersects(street)):
		if street.is_empty or not street.intersects(core):
			return {},{},{"strassenraum_m2":0., "fehlend_m2":0.,"overlap_m2":0.}
		raise ValueError("Straßenmaske oder Kachel ungültig")
	mask=_polygon(street.intersection(core),"Straßenraum innerhalb Kachel")
	if mask is None:
		return {},{},{"strassenraum_m2":0., "fehlend_m2":0.,"overlap_m2":0.}
	junction=_polygon(union_all([node.buffer(radius,resolution=12)
		for node in nodes]).intersection(mask) if nodes else None,
		"Knotenbereich")
	remaining=mask.difference(junction) if junction is not None else mask
	assigned=defaultdict(list)
	special=[]
	# >=2 Sites sind nötig, wenn keine Achse die AOI beeinflusst,
	# wird alles ausdrücklich als Restfläche ausgewiesen.
	if len(sites)>MAX_SITES:
		raise ValueError(f"Über {MAX_SITES} Voronoi-Sites in einer Kachel: "
			"Kachelgröße reduzieren, NICHT den Abtastabstand verändern")
	if len(sites)>=2:
		pts=MultiPoint([(x,y) for _,x,y in sites])
		cells=voronoi_polygons(pts,extend_to=core.envelope.buffer(max_distance+10),
			ordered=True)
		if len(cells.geoms)!=len(sites):
			raise ValueError("Voronoi-Sites und -Zellen nicht bijektiv")
		by_axis=defaultdict(list)
		for cell,(pk,_,_) in zip(cells.geoms,sites):
			if cell.intersects(core):
				by_axis[pk].append(cell)
		# Jede Zelle gehört genau einem GIP-Abschnitt; Reihenfolge
		# ist nur für numerische Rundungsreste relevant.
		for pk in sorted(by_axis):
			axis=axes[pk]
			candidate=_polygon(union_all(by_axis[pk]).intersection(remaining),
				f"Voronoi {axis['id']}")
			if candidate is None:
				continue
			near=_polygon(candidate.intersection(
				axis["geometry"].buffer(max_distance,resolution=8)),
				f"Achsnähe {axis['id']}")
			if near is None:
				continue
			near=_polygon(near.intersection(remaining),
				f"Exklusive Fläche {axis['id']}")
			if near is None:
				continue
			remaining=remaining.difference(near)
			if axis["fow"]==3:
				assigned[axis["id"]].append(near)
			else:
				special.append(near)
	results={gid:_polygon(union_all(geoms),f"GIP {gid}")
		for gid,geoms in assigned.items()}
	unresolved={}
	if junction is not None:
		unresolved["knotenbereich"]=junction
	if special:
		unresolved["sonderachse"]=_polygon(union_all(special),"Sonderachsen")
	rest=_polygon(remaining,"nicht zugeteilt")
	if rest is not None:
		unresolved["nicht_zugeordnet"]=rest
	pieces=list(results.values())+list(unresolved.values())
	combined=union_all(pieces) if pieces else None
	sum_area=sum(g.area for g in pieces)
	overlap=max(0,sum_area-combined.area) if combined is not None else 0
	missing=mask.difference(combined).area if combined is not None else mask.area
	outside=combined.difference(mask).area if combined is not None else 0
	limit=max(.05,mask.area*1e-6)
	if max(overlap,missing,outside,abs(sum_area-mask.area))>limit:
		raise ValueError(f"V0-Kachelbilanz: fehlend {missing:.6f}, "
			f"Überlappung {overlap:.6f}, außerhalb {outside:.6f} m²")
	return results,unresolved,{
		"strassenraum_m2":mask.area,
		"zugeordnet_m2":sum(g.area for g in results.values()),
		"ungeklaert_m2":sum(g.area for g in unresolved.values()),
		"fehlend_m2":missing,"overlap_m2":overlap,
		"ausserhalb_m2":outside,"toleranz_m2":limit,
		"sites":len(sites),"knoten":len(nodes),
	}


def connect_results(path, *, create=False):
	path=Path(path)
	if create:
		path.parent.mkdir(parents=True,exist_ok=True)
		if path.exists():
			raise FileExistsError(f"Ergebnisse existieren: {path}")
	with sqlite3.connect(path) as db:
		if create:
			db.executescript("""
				CREATE TABLE config(key TEXT PRIMARY KEY,value TEXT NOT NULL);
				CREATE TABLE tiles(id TEXT PRIMARY KEY,street_sha256 TEXT NOT NULL,
					area REAL NOT NULL,assigned REAL NOT NULL,
					unresolved REAL NOT NULL,elapsed_s REAL NOT NULL,
					stats_json TEXT NOT NULL);
				CREATE TABLE parts(tile_id TEXT NOT NULL,
					kind TEXT NOT NULL,gip_id TEXT NOT NULL,
					area REAL NOT NULL, geom BLOB NOT NULL,
					PRIMARY KEY(tile_id,kind,gip_id));
				CREATE INDEX parts_by_gid ON parts(gip_id);
			""")
	# sqlite connections cannot be returned via context manager above.
	return sqlite3.connect(path)


def write_tile(db, tile_id, street_sha, assignments, unresolved, stats, elapsed):
	if db.execute("SELECT 1 FROM tiles WHERE id=?",(tile_id,)).fetchone():
		raise FileExistsError(f"Ergebnis-Kachel existiert schon: {tile_id}")
	with db:
		db.execute("""INSERT INTO tiles VALUES (?,?,?,?,?,?,?)""",(
			tile_id,street_sha,stats["strassenraum_m2"],
			stats["zugeordnet_m2"],stats["ungeklaert_m2"],elapsed,
			json.dumps(stats,ensure_ascii=False)))
		for kind,mapping in (("abschnitt",assignments),("ungeklaert",unresolved)):
			for gid,geom in mapping.items():
				if geom is None or not geom.is_valid or geom.area<=0:
					raise ValueError(f"Ungültiger Ergebnisteil {tile_id}:{kind}:{gid}")
				db.execute("INSERT INTO parts VALUES (?,?,?,?,?)",(
					tile_id,kind,gid,geom.area,dumps(geom)))


def report_results(db, manifest):
	items=db.execute("SELECT id,area,assigned,unresolved,elapsed_s FROM tiles").fetchall()
	ids={row[0] for row in items}
	expected={t["id"] for t in manifest["tiles"]}
	if ids!=expected:
		raise ValueError(f"Unvollständiger Wien-Lauf: "
			f"{len(expected-ids)} Kacheln fehlen, {len(ids-expected)} unerwartet")
	area=sum(r[1] for r in items)
	assigned=sum(r[2] for r in items)
	unresolved=sum(r[3] for r in items)
	# Kacheln sind disjunkt; Flächenbeiträge werden je GIP-ID
	# zusammengefasst, ohne Geometrie über die Kachel hinweg
	# im Speicher vereinigen zu müssen.
	groups=db.execute("""
		SELECT kind,gip_id,COUNT(*),SUM(area)
		FROM parts GROUP BY kind,gip_id ORDER BY kind,gip_id
	""").fetchall()
	tot=assigned+unresolved
	if abs(tot-area)>max(.05,area*1e-6):
		raise ValueError(f"Wienweite Ergebnisbilanz fehlerhaft: {tot-area} m²")
	return {"schema_version":SCHEMA,"status":"vorläufige V0-Aufteilung; "
		"keine fachlich geprüfte Straßenabgrenzung",
		"kacheln":len(items),"strassenraum_m2":area,
		"abschnitte_m2":assigned,"ungeklaert_m2":unresolved,
		"bilanzdifferenz_m2":tot-area,
		"geometrisch_eindeutige_gip_ids":sum(1 for r in groups if r[0]=="abschnitt"),
		"klassengruppen":{key:sum(r[3] for r in groups
			if r[0]=="ungeklaert" and r[1]==key) for key in GROUPS},
		"laufzeit_s":sum(r[4] for r in items),
		"hinweis":"Kachelgrenzen nur rechnerische Arbeitsbereiche; jede "
			"GIP-ID bleibt über sämtliche Kacheln identisch. "
			"Flächen sind ohne Überlagerung geschnitten.",
	}


def run(manifest_path, gip_path, street_root, output, *, limit_tiles=None):
	manifest,aoi=read_manifest(manifest_path)
	street_root,output=Path(street_root),Path(output)
	from scripts.wienwide_street import load_street_tile
	with connect_gip(gip_path) as gip:
		metadata=dict((r["key"],json.loads(r["value"]))
			for r in gip.execute("SELECT key,value FROM meta"))
		if (metadata.get("manifest_sha256")!=checksum(manifest_path)
			or metadata.get("sampling_m")!=5
			or metadata.get("knotenradius_m")!=7
			or metadata.get("max_axis_distance_m")!=25):
			raise ValueError("GIP-Katalog gehört zu anderem AOI/anderer V0-Methodik")
		tiles=manifest["tiles"]
		if limit_tiles is not None:
			if limit_tiles<1:raise ValueError("limit_tiles muss positiv sein")
			tiles=tiles[:limit_tiles]
		is_new=not output.exists()
		with connect_results(output,create=is_new) as target:
			orig_config=dict(target.execute("SELECT key,value FROM config"))
			expected={"manifest_sha256":checksum(manifest_path),
				"gip_sha256":checksum(gip_path),"schema_version":str(SCHEMA)}
			if not orig_config:
				with target:
					for key,value in expected.items():
						target.execute("INSERT INTO config VALUES (?,?)",(key,value))
			elif orig_config!=expected:
				raise ValueError("Bestehende Ausgabe gehört zu anderen GIP/AOI-Quellen")
			for i,tile in enumerate(tiles,1):
				source=street_root/tile["id"]/"street.sqlite"
				if not source.is_file():
					raise FileNotFoundError(f"Metrische Straßenraumkachel fehlt: {source}")
				sha=checksum(source)
				existing=target.execute("SELECT street_sha256 FROM tiles WHERE id=?",
					(tile["id"],)).fetchone()
				if existing:
					if existing[0]!=sha:
						raise ValueError(f"Geänderte Straßenraumquelle für {tile['id']}")
					print(f"Überspringe bereits geprüfte Kachel {tile['id']}")
					continue
				start=perf_counter()
				core=box(*tile["bounds_31256"]).intersection(aoi)
				street=load_street_tile(source,core)
				sites,axes,nodes=graph_context(gip,tile["bounds_31256"],
					halo=manifest["halo_m"])
				results,unknown,stats=split_tile(street,core,sites,axes,nodes)
				elapsed=perf_counter()-start
				write_tile(target,tile["id"],sha,results,unknown,stats,elapsed)
				print(f"{i}/{len(tiles)} {tile['id']}: "
					f"{stats['strassenraum_m2']:.1f} m², "
					f"{stats['zugeordnet_m2']:.1f} m² zugeordnet, "
					f"{elapsed:.2f}s")
			count=target.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
			complete=count==len(manifest["tiles"])
			if complete:
				return report_results(target,manifest)
			return {"status":"PARTIELL – NICHT WIENWEIT VOLLSTÄNDIG",
				"fertige_kacheln":count,"gesamt_kacheln":len(manifest["tiles"])}


def main():
	p=argparse.ArgumentParser(description=__doc__)
	p.add_argument("--manifest",type=Path,required=True)
	p.add_argument("--gip-index",type=Path,required=True)
	p.add_argument("--street-root",type=Path,required=True)
	p.add_argument("--out",type=Path,required=True)
	p.add_argument("--limit-tiles",type=int,help="Begrenzter Diagnoselauf")
	args=p.parse_args()
	try:
		report=run(args.manifest,args.gip_index,args.street_root,args.out,
			limit_tiles=args.limit_tiles)
		print(json.dumps(report,ensure_ascii=False,indent=2))
	except (OSError,ValueError,TypeError,KeyError,sqlite3.Error) as exc:
		p.exit(1,f"Fehler: {exc}\n")


if __name__=="__main__":
	main()
