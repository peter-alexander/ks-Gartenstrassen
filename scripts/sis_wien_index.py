"""Importiert komprimierte Wiener SIS-WFS-Kacheln in eine deduplizierte SQLite.

Rohkacheln und Ziel-DB liegen standardmäßig auf /mnt/e. Jede Kachel
wird mit allen Features atomar importiert; Dubletten erfordern identische
Attribute und Geometrien. Features werden niemals am WFS-Rand gekürzt.
"""
import argparse
import hashlib
import json
import lzma
from pathlib import Path
import sqlite3

from shapely.geometry import shape
from shapely.ops import transform
from shapely.wkb import dumps

from scripts.sis_belagsflaechen import TO_METRIC, _repair_source_polygon
from scripts.sis_wien_wfs import feature_identity, fetch_tile, tiles, validate
from scripts.wienwide_grid import load_aoi

DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "data" / "wien"
SCHEMA = "sis-wien-index-v1"


def connect(path):
	path = Path(path)
	path.parent.mkdir(parents=True, exist_ok=True)
	db = sqlite3.connect(path)
	db.execute("PRAGMA busy_timeout=30000")
	db.execute("PRAGMA journal_mode=DELETE")
	db.execute("PRAGMA foreign_keys=ON")
	db.executescript("""
		CREATE TABLE IF NOT EXISTS metadata(
			key TEXT PRIMARY KEY, value TEXT NOT NULL);
		CREATE TABLE IF NOT EXISTS features(
			id INTEGER PRIMARY KEY, source_id TEXT NOT NULL UNIQUE,
			signature TEXT NOT NULL, type TEXT NOT NULL,
			belag TEXT NOT NULL, belag_txt TEXT NOT NULL,
			area_m2 REAL NOT NULL, geom BLOB NOT NULL);
		CREATE VIRTUAL TABLE IF NOT EXISTS feature_index USING rtree(
			id,minx,maxx,miny,maxy);
		CREATE TABLE IF NOT EXISTS imported_tiles(
			tile_id TEXT PRIMARY KEY, source_sha256 TEXT NOT NULL,
			bbox_json TEXT NOT NULL, source_features INTEGER NOT NULL,
			new_features INTEGER NOT NULL, duplicate_features INTEGER NOT NULL);
	""")
	existing = dict(db.execute("SELECT key,value FROM metadata"))
	if existing and existing.get("schema") != SCHEMA:
		db.close()
		raise ValueError("Unbekanntes oder widersprüchliches SIS-SQLite-Schema")
	if not existing:
		with db:
			db.executemany("INSERT INTO metadata VALUES (?,?)", [
				("schema", SCHEMA),("provider","SISBELAGOGD"),
				("crs","EPSG:31256"),("source","WFS-cached-XZ"),
			])
	return db


def import_tile(db, tile_id, bbox, path):
	path = Path(path)
	raw_compressed = path.read_bytes()
	source_sha = hashlib.sha256(raw_compressed).hexdigest()
	existing = db.execute("SELECT source_sha256,bbox_json FROM imported_tiles "
		"WHERE tile_id=?", (tile_id,)).fetchone()
	bbox_json = json.dumps(list(bbox))
	if existing:
		if existing != (source_sha, bbox_json):
			raise ValueError(f"{tile_id}: vorhandener Import verwendet andere Quelldaten")
		return {"tile":tile_id,"status":"vorhanden"}
	with lzma.open(path,"rb") as source:
		raw = source.read()
	doc = validate(raw, tile=tile_id)
	new = duplicate = 0
	# Vollständige Featuregeometrie unverändert im lokalen Index ablegen.
	with db:
		for i,feature in enumerate(doc["features"]):
			props = feature["properties"]
			sid = feature_identity(feature)
			geom = shape(feature["geometry"])
			if not geom.is_valid:
				from shapely.validation import explain_validity
				geom, _ = _repair_source_polygon(geom,index=i,
					identifier=sid,sis_id=props.get("SIS_ID"),
					reason=explain_validity(geom))
			if geom.is_empty or geom.geom_type not in ("Polygon","MultiPolygon"):
				raise ValueError(f"{tile_id}/{sid}: keine Polygongeometrie")
			metric = transform(TO_METRIC,geom)
			if not metric.is_valid or metric.area <= 0:
				raise ValueError(f"{tile_id}/{sid}: ungültige metrische Fläche")
			binary = dumps(metric)
			signature = hashlib.sha256(json.dumps({
				"properties":props,"geometry":feature["geometry"]},
				sort_keys=True,separators=(",",":"),ensure_ascii=False
			).encode("utf-8")).hexdigest()
			old = db.execute("SELECT signature FROM features "
				"WHERE source_id=?", (sid,)).fetchone()
			if old:
				if old[0] != signature:
					raise ValueError(f"{tile_id}/{sid}: widersprüchliche Dublette")
				duplicate += 1
				continue
			cursor = db.execute("INSERT INTO features "
				"(source_id,signature,type,belag,belag_txt,area_m2,geom) "
				"VALUES (?,?,?,?,?,?,?)",
				(sid,signature,props["TYPE"],props["BELAG"],
					props["BELAG_TXT"],metric.area,binary))
			x0,y0,x1,y1 = metric.bounds
			db.execute("INSERT INTO feature_index VALUES (?,?,?,?,?)",
				(cursor.lastrowid,x0,x1,y0,y1))
			new += 1
		db.execute("INSERT INTO imported_tiles VALUES (?,?,?,?,?,?)",
			(tile_id,source_sha,bbox_json,len(doc["features"]),new,duplicate))
	return {"tile":tile_id,"status":"importiert","neu":new,"duplikate":duplicate}


def verify_complete(db, grid):
	"""Explizite Vollständigkeitsprüfung vor Freigabe der Analyse."""
	expected = {name: json.dumps(list(bounds)) for name,bounds in grid}
	actual = {name: bbox for name,bbox in db.execute(
		"SELECT tile_id,bbox_json FROM imported_tiles")}
	if expected != actual:
		missing = sorted(set(expected) - set(actual))
		excess = sorted(set(actual) - set(expected))
		changed = sorted(name for name in set(expected) & set(actual)
			if expected[name] != actual[name])
		raise ValueError(f"SIS-Wien-Import unvollständig oder abweichend: "
			f"fehlend={missing[:5]}, zusätzlich={excess[:5]}, "
			f"abweichende BBOX={changed[:5]}")
	if db.execute("SELECT COUNT(*) FROM feature_index").fetchone()[0] != (
			db.execute("SELECT COUNT(*) FROM features").fetchone()[0]):
		raise ValueError("SIS-R-Tree unvollständig")
	return True


def run(aoi_path, cache, database):
	aoi = load_aoi(aoi_path)
	grid = list(tiles(aoi))
	if not grid:
		raise ValueError("AOI enthält keine WFS-Kacheln")
	stats = {"kacheln":len(grid),"neu_importiert":0,"wiederverwendet":0,
		"neue_features":0,"duplikate":0}
	with connect(database) as db:
		for i,(name,bounds) in enumerate(grid,1):
			path,count,downloaded = fetch_tile(name,bounds,Path(cache))
			result = import_tile(db,name,bounds,path)
			if result["status"] == "vorhanden":
				stats["wiederverwendet"] += 1
			else:
				stats["neu_importiert"] += 1
				stats["neue_features"] += result["neu"]
				stats["duplikate"] += result["duplikate"]
			print(f"{i}/{len(grid)} {name}: {count} WFS-Features, "
				f"{result['status']}, {'neu' if downloaded else 'XZ-Cache'}",
				flush=True)
		verify_complete(db,grid)
		# Versionierter Fingerabdruck der vollständig importierten Quellkacheln.
		rows = db.execute("SELECT tile_id,source_sha256,bbox_json "
			"FROM imported_tiles ORDER BY tile_id").fetchall()
		digest = hashlib.sha256(json.dumps(rows,separators=(",",":")).encode()).hexdigest()
		with db:
			db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)",
				("sha256",digest))
		stats["gesamte_eindeutige_features"] = db.execute(
			"SELECT COUNT(*) FROM features").fetchone()[0]
		stats["gesamte_importierte_kacheln"] = db.execute(
			"SELECT COUNT(*) FROM imported_tiles").fetchone()[0]
	return stats


def main():
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("--aoi",type=Path,required=True)
	p.add_argument("--cache",type=Path,
		default=DEFAULT_ROOT/"wfs-kacheln")
	p.add_argument("--database",type=Path,
		default=DEFAULT_ROOT/"sis-wien.sqlite")
	a = p.parse_args()
	print(json.dumps(run(a.aoi,a.cache,a.database),
		ensure_ascii=False,indent=2))


if __name__ == "__main__":
	main()
