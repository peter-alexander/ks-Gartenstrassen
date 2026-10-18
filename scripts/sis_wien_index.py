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
from scripts.sis_wien_wfs import feature_identity, fetch_tile_parts, tiles, validate
from scripts.wienwide_grid import load_aoi

DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "data" / "wien"
SCHEMA = "sis-wien-index-v5"
# Der WFS liefert für dieselbe SIS-Geometrie wechselnde Java-Referenzen
# statt fachlicher Daten. Dieser eine volatile Wert bleibt im Rohcache,
# gehört aber nicht in die Gleichheitsprüfung einer Quell-Dublette.
VOLATILE_SIGNATURE_PROPERTIES = frozenset(("SE_ANNO_CAD_DATA",))
MISSING_BELAG_CODE = "__SIS_BELAG_FEHLT__"
MISSING_BELAG_TEXT = "fehlender SIS-Belag; konservativ nicht begrünt"
MISSING_TYPE_CODE = "__SIS_TYPE_FEHLT__"


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
		CREATE TABLE IF NOT EXISTS excluded_features(
			source_id TEXT PRIMARY KEY, signature TEXT NOT NULL,
			tile_id TEXT NOT NULL, feature_index INTEGER NOT NULL,
			sis_id TEXT, missing_fields_json TEXT NOT NULL,
			geom_type TEXT NOT NULL, metric_area_m2 REAL NOT NULL,
			reason TEXT NOT NULL);
		CREATE TABLE IF NOT EXISTS classification_events(
			source_id TEXT PRIMARY KEY, signature TEXT NOT NULL,
			tile_id TEXT NOT NULL, feature_index INTEGER NOT NULL,
			sis_id TEXT, missing_fields_json TEXT NOT NULL,
			metric_area_m2 REAL NOT NULL, treatment TEXT NOT NULL);
	""")
	existing = dict(db.execute("SELECT key,value FROM metadata"))
	if existing and existing.get("schema") != SCHEMA:
		db.close()
		raise ValueError("SIS-Wien-Index hat einen älteren Vertragsstand und muss "
			"aus dem unveränderten WFS-Cache neu aufgebaut werden")
	if not existing:
		with db:
			db.executemany("INSERT INTO metadata VALUES (?,?)", [
				("schema", SCHEMA),("provider","SISBELAGOGD"),
				("crs","EPSG:31256"),("source","WFS-cached-XZ"),
			])
	return db


def _missing_classification(props):
	return [field for field in ("TYPE","BELAG","BELAG_TXT")
		if not isinstance(props.get(field),str) or not props[field].strip()]


def _feature_signature(feature):
	"""Stabile Gleichheit ohne die belegte volatile WFS-Java-Referenz."""
	props = {key:value for key,value in feature["properties"].items()
		if key not in VOLATILE_SIGNATURE_PROPERTIES}
	return hashlib.sha256(json.dumps({
		"properties":props,"geometry":feature["geometry"]},
		sort_keys=True,separators=(",",":"),ensure_ascii=False
	).encode("utf-8")).hexdigest()


def _record_excluded_feature(db, *, tile_id, index, sid, signature, props,
		geom, metric_area, missing):
	"""Auditierte Ausnahme ausschließlich für unklassifizierbare Mikroartefakte."""
	if metric_area > UNCLASSIFIED_AREA_TOLERANCE_M2:
		raise ValueError(f"{tile_id}/{sid}: SIS-Klassifikation fehlt ({','.join(missing)}), "
			f"aber Fläche {metric_area:.9f} m² übersteigt die zulässige "
			f"Mikroartefaktgrenze {UNCLASSIFIED_AREA_TOLERANCE_M2:.2f} m²")
	if db.execute("SELECT 1 FROM features WHERE source_id=?",(sid,)).fetchone():
		raise ValueError(f"{tile_id}/{sid}: Klassifikation widerspricht bereits importiertem SIS-Feature")
	old = db.execute("SELECT signature FROM excluded_features WHERE source_id=?",
		(sid,)).fetchone()
	if old:
		if old[0] != signature:
			raise ValueError(f"{tile_id}/{sid}: widersprüchliches unklassifiziertes Mikroartefakt")
		return False
	db.execute("INSERT INTO excluded_features "
		"(source_id,signature,tile_id,feature_index,sis_id,missing_fields_json,"
		"geom_type,metric_area_m2,reason) VALUES (?,?,?,?,?,?,?,?,?)",
		(sid,signature,tile_id,index,props.get("SIS_ID"),json.dumps(missing),
		geom.geom_type,metric_area,"fehlende_SIS_Klassifikation_unter_Flaechentoleranz"))
	return True


def _record_missing_belag(db, *, tile_id, index, sid, signature, props,
		metric_area, missing, treatment):
	"""Auditiere eine Klassifikationslücke, ohne SIS-Fläche zu verlieren."""
	if db.execute("SELECT 1 FROM excluded_features WHERE source_id=?",(sid,)).fetchone():
		raise ValueError(f"{tile_id}/{sid}: BELAG widerspricht ausgeschlossenem SIS-Mikroartefakt")
	old = db.execute("SELECT signature FROM classification_events WHERE source_id=?",
		(sid,)).fetchone()
	if old:
		if old[0] != signature:
			raise ValueError(f"{tile_id}/{sid}: widersprüchliche SIS-Klassifikationslücke")
		return False
	db.execute("INSERT INTO classification_events "
		"(source_id,signature,tile_id,feature_index,sis_id,missing_fields_json,"
		"metric_area_m2,treatment) VALUES (?,?,?,?,?,?,?,?)",
		(sid,signature,tile_id,index,props.get("SIS_ID"),json.dumps(missing),
		metric_area,treatment))
	return True


def import_tile(db, tile_id, bbox, paths):
	paths = [Path(paths)] if isinstance(paths,(str,Path)) else [Path(path) for path in paths]
	if not paths:
		raise ValueError(f"{tile_id}: keine SIS-WFS-Quelldatei")
	source_sha = hashlib.sha256(json.dumps([
		(path.name,hashlib.sha256(path.read_bytes()).hexdigest()) for path in paths],
		separators=(",",":")).encode()).hexdigest()
	existing = db.execute("SELECT source_sha256,bbox_json FROM imported_tiles "
		"WHERE tile_id=?", (tile_id,)).fetchone()
	bbox_json = json.dumps(list(bbox))
	if existing:
		if existing != (source_sha, bbox_json):
			raise ValueError(f"{tile_id}: vorhandener Import verwendet andere Quelldaten")
		return {"tile":tile_id,"status":"vorhanden"}
	docs = []
	for path in paths:
		with lzma.open(path,"rb") as source:
			raw = source.read()
		docs.append(validate(raw, tile=path.name))
	features = [feature for doc in docs for feature in doc["features"]]
	new = duplicate = excluded = missing_belag = 0
	# Vollständige Featuregeometrie unverändert im lokalen Index ablegen.
	with db:
		for i,feature in enumerate(features):
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
			signature = _feature_signature(feature)
			missing = _missing_classification(props)
			if missing:
				# TYPE grenzt den V2-Straßenraum ausdrücklich nicht ein. Ein
				# fehlender TYPE darf daher nie Fläche aus dem Nenner entfernen.
				# Fehlt der Belag selbst, ist die einzige konservative Lesart
				# „nicht begrünt“; eine vorhandene Belagsangabe bleibt erhalten.
				treatment = "fehlender_TYPE_im_Strassenraum_erhalten"
				props = dict(props)
				if "TYPE" in missing:
					props["TYPE"] = MISSING_TYPE_CODE
				if "BELAG" in missing or "BELAG_TXT" in missing:
					props["BELAG"] = MISSING_BELAG_CODE
					props["BELAG_TXT"] = MISSING_BELAG_TEXT
					treatment = "fehlender_BELAG_konservativ_nicht_begruent"
				missing_belag += _record_missing_belag(db,tile_id=tile_id,index=i,
					sid=sid,signature=signature,props=props,
					metric_area=metric.area,missing=missing,treatment=treatment)
			old = db.execute("SELECT signature FROM features "
				"WHERE source_id=?", (sid,)).fetchone()
			if old:
				if old[0] != signature:
					raise ValueError(f"{tile_id}/{sid}: widersprüchliche Dublette")
				duplicate += 1
				continue
			if db.execute("SELECT 1 FROM excluded_features WHERE source_id=?",(sid,)).fetchone():
				raise ValueError(f"{tile_id}/{sid}: Klassifikation widerspricht bereits auditiertem Mikroartefakt")
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
			(tile_id,source_sha,bbox_json,len(features),new,duplicate))
	return {"tile":tile_id,"status":"importiert","neu":new,"duplikate":duplicate,
		"ausgeschlossen":excluded,"fehlender_belag":missing_belag}


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
		"neue_features":0,"duplikate":0,"ausgeschlossene_mikroartefakte":0,
		"fehlender_belag_konservativ_nicht_begruent":0}
	with connect(database) as db:
		for i,(name,bounds) in enumerate(grid,1):
			parts,count,downloaded = fetch_tile_parts(name,bounds,Path(cache))
			result = import_tile(db,name,bounds,[path for path,_,_ in parts])
			if result["status"] == "vorhanden":
				stats["wiederverwendet"] += 1
			else:
				stats["neu_importiert"] += 1
				stats["neue_features"] += result["neu"]
				stats["duplikate"] += result["duplikate"]
				stats["ausgeschlossene_mikroartefakte"] += result["ausgeschlossen"]
				stats["fehlender_belag_konservativ_nicht_begruent"] += result["fehlender_belag"]
			print(f"{i}/{len(grid)} {name}: {count} WFS-Features "
				f"aus {len(parts)} Teilabfrage(n), {result['status']}, "
				f"{'neu' if downloaded else 'XZ-Cache'}",
				flush=True)
		verify_complete(db,grid)
		# Versionierter Fingerabdruck der vollständig importierten Quellkacheln.
		rows = db.execute("SELECT tile_id,source_sha256,bbox_json "
			"FROM imported_tiles ORDER BY tile_id").fetchall()
		excluded = db.execute("SELECT source_id,signature,metric_area_m2 "
			"FROM excluded_features ORDER BY source_id").fetchall()
		classification_events = db.execute("SELECT source_id,signature,metric_area_m2 "
			"FROM classification_events ORDER BY source_id").fetchall()
		digest = hashlib.sha256(json.dumps({"schema":SCHEMA,"tiles":rows,
			"excluded_features":excluded,
			"classification_events":classification_events},
			separators=(",",":")).encode()).hexdigest()
		with db:
			db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)",
				("sha256",digest))
			db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)",
				("excluded_features",str(len(excluded))))
			db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)",
				("excluded_area_m2",repr(sum(row[2] for row in excluded))))
			db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)",
				("missing_belag_features",str(len(classification_events))))
			db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)",
				("missing_belag_area_m2",repr(sum(row[2] for row in classification_events))))
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
