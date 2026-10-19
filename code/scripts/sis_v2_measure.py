"""Abschnittsbezogene SIS-V2-Messung mit GIP-Flächen und optional GRM2023.

Alle SIS-TYPE-Flächen zählen; BELAG BL/ST/WI gelten als Bodenbegrünung.
Alle übrigen Beläge sind nicht begrünt.
Keine FMZK-/Kataster-Abhängigkeiten, keine stillen NULL->0-Umwandlungen.
"""
import argparse
from collections import defaultdict
from contextlib import closing
import csv
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from time import monotonic

from pyproj import Transformer
from shapely import union_all
from shapely.geometry import box, mapping
from shapely.ops import transform
from shapely.wkb import loads

from scripts.sis_belagsflaechen import VEGETATION_CODES
from scripts.sis_v2_street import VERSION
from scripts.wienwide_grid import checksum, read_manifest
from scripts.wienwide_partition import report_results
from scripts.wienwide_gip import connect as connect_gip
from scripts.wienwide_grm2023 import read_mask as read_grm

TO_WGS = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform
VEGETATION = VEGETATION_CODES
FIELDS = ("gip_id", "strassenname", "fow", "abschnitt_flaeche_m2",
	"boden_m2", "boden_pct", "nicht_begruent_m2",
	"nicht_begruent_pct", "grm_kronen_m2", "grm_kronen_pct", "kachelteile", "original_gip_ids")


def _mask(db, core, categories):
	city = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='features'").fetchone() is not None
	if city:
		from scripts.sis_wien_source import mask as city_mask
		return city_mask(db,core,categories)
	parts = []
	for kind, blob in db.execute("SELECT belag,geom FROM surfaces"):
		if kind not in categories:
			continue
		geom = loads(blob)
		if geom.intersects(core):
			intersection = geom.intersection(core)
			if not intersection.is_empty and intersection.area > 0:
				parts.append(intersection)
	return union_all(parts) if parts else None


def _vegetation_mask(db, core, *, city=None):
	"""Nur eindeutig begrünte SIS-Fläche; Quellkonflikte konservativ abziehen."""
	if city is None:
		city = db.execute(
			"SELECT 1 FROM sqlite_master WHERE type='table' AND name='features'"
		).fetchone() is not None
	if city:
		from scripts.sis_wien_source import vegetation_mask as city_vegetation_mask
		return city_vegetation_mask(db, core, VEGETATION)
	# Kompatibilität mit den bisherigen kleinen SIS-Pilotdaten.
	green = _mask(db, core, VEGETATION)
	if green is None:
		return None
	non_green = _mask(db, core, {row[0] for row in db.execute(
		"SELECT DISTINCT belag FROM surfaces") if row[0] not in VEGETATION})
	return green.difference(non_green) if non_green is not None else green


def _duration(seconds):
	seconds = max(0, int(seconds))
	hours, remainder = divmod(seconds, 3600)
	minutes, seconds = divmod(remainder, 60)
	return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _intersect_area(part, mask):
	return part.intersection(mask).area if mask is not None else 0.


def _grm_source_fingerprint(tiles, grm_root):
	"""SHA-256-gebundener Nachweis der GRM-Masken für alle Kacheln."""
	if grm_root is None:
		return None
	entries = sorted((tile["id"],checksum(Path(grm_root)/"masken"/tile["id"]/"crown.sqlite"))
		for tile in tiles)
	return hashlib.sha256(json.dumps(entries,separators=(",",":")).encode()).hexdigest()


def run(manifest_path, gip_path, sis_path, street_root, partition_path,
		out_dir, grm_root=None, grm_raw_root=None, *, resume=False):
	manifest, aoi = read_manifest(manifest_path)
	manifest_sha = checksum(manifest_path)
	out_dir, sis_path = Path(out_dir), Path(sis_path)
	if out_dir.exists() and not resume:
		raise FileExistsError(out_dir)
	checkpoint_path = out_dir.parent / "messung.sqlite"
	stage = out_dir.with_name(out_dir.name + ".tmp")
	if stage.exists():
		if stage.is_symlink() or not stage.is_dir():
			raise FileExistsError(stage)
		# Unvollständiger temporärer Export kann erneut erzeugt werden.
		shutil.rmtree(stage)
	with sqlite3.connect(f"file:{sis_path.resolve()}?mode=ro", uri=True) as sis, \
			sqlite3.connect(f"file:{Path(partition_path).resolve()}?mode=ro", uri=True) as partition, \
			connect_gip(gip_path) as gip, \
			closing(sqlite3.connect(checkpoint_path)) as checkpoint:
		meta = dict(sis.execute("SELECT key,value FROM metadata"))
		if meta.get("crs") != "EPSG:31256" or meta.get("provider") != "SISBELAGOGD":
			raise ValueError("Ungültiger SIS-Index")
		config = dict(partition.execute("SELECT key,value FROM config"))
		config.pop("querschnitt_regel",None)
		gip_sha = checksum(gip_path)
		partition_sha = checksum(partition_path)
		expected = {"schema_version":"1", "manifest_sha256":manifest_sha,
			"gip_sha256":gip_sha}
		if config not in ({**expected,"junction_policy":"none","fow_policy":"all"},
			{**expected,"junction_policy":"gip2-turn-use-convex-hull","fow_policy":"all"},
			{**expected,"junction_policy":"voronoi-stable-width-v1","fow_policy":"all"}):
			raise ValueError("SIS V2 benötigt eine unterstützte Voronoi-Partition")
		if out_dir.exists():
			report = json.loads((out_dir/"bericht.json").read_text(encoding="utf-8"))
			if (report.get("manifest_sha256") != manifest_sha
				or report.get("sis_source_sha256") != meta["sha256"]
				or report.get("gip_sha256") != gip_sha
				or report.get("partition_sha256") != partition_sha
				or report.get("grm_available") != (grm_root is not None)
				or report.get("grm_masks_sha256") != _grm_source_fingerprint(
					manifest["tiles"], grm_root)):
				raise ValueError("Vorhandene Messausgabe gehört zu anderen Eingaben")
			for name,key in (("gip_abschnitte.csv","csv_sha256"),
					("gip_abschnitte.geojson","geojson_sha256")):
				if key not in report or checksum(out_dir/name) != report[key]:
					raise ValueError(f"Messausgabe beschädigt: {name}")
			print("SIS V2 measure: fertiges GeoJSON und CSV wiederverwendet",
				flush=True)
			return report
		balance = report_results(partition,manifest)
		axes = {str(gid):(name,fow) for gid,name,fow in gip.execute(
			"SELECT gip,name,fow FROM axes")}
		grouping = gip.execute("SELECT name FROM sqlite_master WHERE "
			"name='merged_members'").fetchone() is not None
		member_ids = defaultdict(list)
		if grouping:
			for original,rep in gip.execute(
				"SELECT original_id,representative_id FROM merged_members "
				"ORDER BY representative_id,original_id"):
				member_ids[rep].append(original)
		groups = defaultdict(lambda:{"area":0.,"vegetation":0.,
			"crown":0.,"parts":0,"geometries":[]})
		checkpoint.execute("PRAGMA journal_mode=DELETE")
		checkpoint.executescript("""
			CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
			CREATE TABLE IF NOT EXISTS tiles(
				tile_id TEXT PRIMARY KEY, street_sha TEXT NOT NULL,
				grm_sha TEXT NOT NULL, contributions_json TEXT NOT NULL);
		""")
		contract = {"schema":"sis-v2-measure-checkpoint-v1",
			"manifest_sha256":manifest_sha,"sis_source_sha256":meta["sha256"],
			"gip_sha256":gip_sha,"partition_sha256":partition_sha,
			"with_grm":str(grm_root is not None)}
		stored = dict(checkpoint.execute("SELECT key,value FROM metadata"))
		if stored and stored != contract:
			raise ValueError("Messcheckpoint gehört zu anderen Quellen")
		if not stored:
			with checkpoint:
				checkpoint.executemany("INSERT INTO metadata VALUES (?,?)",contract.items())
		is_city_sis = sis.execute(
			"SELECT 1 FROM sqlite_master WHERE type='table' AND name='features'"
		).fetchone() is not None
		tile_count = len(manifest["tiles"])
		started = monotonic()
		for tile_number, tile in enumerate(manifest["tiles"], 1):
			tid = tile["id"]
			core = box(*tile["bounds_31256"]).intersection(aoi)
			street_path = Path(street_root)/tid/"street.sqlite"
			street_sha = checksum(street_path)
			psha = partition.execute("SELECT street_sha256 FROM tiles WHERE id=?",
				(tid,)).fetchone()
			if psha is None or psha[0] != street_sha:
				raise ValueError(f"{tid}: Partition für andere Straßenraumkachel")
			grm_sha = (checksum(Path(grm_root)/"masken"/tid/"crown.sqlite")
				if grm_root is not None else "")
			cached = checkpoint.execute(
				"SELECT street_sha,grm_sha,contributions_json FROM tiles WHERE tile_id=?",
				(tid,)).fetchone()
			if cached is not None:
				if cached[:2] != (street_sha,grm_sha):
					raise ValueError(f"{tid}: Messcheckpoint für andere Straßenraum-/GRM-Daten")
				metrics = {gid:(area,veg,crown) for gid,area,veg,crown in
					json.loads(cached[2])}
				count = 0
				for gid,stored_area,blob in partition.execute(
					"SELECT gip_id,area,geom FROM parts WHERE tile_id=? AND kind='abschnitt'",(tid,)):
					gid = str(gid)
					if gid not in metrics or abs(metrics[gid][0]-stored_area) > max(.01,stored_area*1e-8):
						raise ValueError(f"{tid}/{gid}: Messcheckpoint passt nicht zur Partition")
					item = groups[gid]
					item["area"] += stored_area
					item["vegetation"] += metrics[gid][1]
					item["crown"] += metrics[gid][2]
					item["parts"] += 1
					item["geometries"].append(loads(blob))
					count += 1
				if count != len(metrics):
					raise ValueError(f"{tid}: Messcheckpoint unvollständig")
				if tile_number == 1 or tile_number % 50 == 0 or tile_number == tile_count:
					print(f"SIS V2 measure {tile_number}/{tile_count}: "
						f"Checkpoint wiederverwendet | Laufzeit {_duration(monotonic()-started)}",
						flush=True)
				continue
			with sqlite3.connect(f"file:{street_path.resolve()}?mode=ro", uri=True) as street:
				street_meta = dict(street.execute("SELECT key,value FROM metadata"))
				if (street_meta.get("strassenraum_regel_version") != VERSION
					or street_meta.get("sis_sha256") != meta["sha256"]
					or street_meta.get("manifest_sha256") != manifest_sha):
					raise ValueError(f"{tid}: unerwartete Straßenraumquelle")
				street_geom = loads(street.execute("SELECT geom FROM street").fetchone()[0])
				if not street_geom.is_valid or street_geom.difference(core).area > .01:
					raise ValueError(f"{tid}: Straßenraum ungültig")
			vegetation = _vegetation_mask(sis,core,city=is_city_sis)
			crown = None
			if grm_root is not None:
				crown, _ = read_grm(grm_root,tile,manifest=manifest_path,aoi=aoi,
					manifest_sha256=manifest_sha,raw_root=grm_raw_root)
			contributions = []
			for gid,stored_area,blob in partition.execute(
				"SELECT gip_id,area,geom FROM parts WHERE tile_id=? AND kind='abschnitt'", (tid,)):
				gid = str(gid)
				if gid not in axes:
					raise ValueError(f"{tid}/{gid}: GIP-Achse fehlt")
				part = loads(blob)
				if (not part.is_valid or part.is_empty or
					abs(part.area-stored_area) > max(.01,stored_area*1e-8) or
					part.difference(street_geom).area > .01):
					raise ValueError(f"{tid}/{gid}: Geometrie nicht in SIS-Straßenraum")
				v = _intersect_area(part,vegetation)
				c = _intersect_area(part,crown) if crown is not None else 0.
				if max(v,c) > stored_area + .01:
					raise ValueError(f"{tid}/{gid}: Belags-/Kronenfläche zu groß")
				item = groups[gid]
				item["area"] += stored_area
				item["vegetation"] += v
				item["crown"] += c
				item["parts"] += 1
				item["geometries"].append(part)
				contributions.append((gid,stored_area,v,c))
			# Abschlussmarker und Kennzahlen atomar; nach einem Abbruch
			# kann ausschließlich die unvollendete Kachel neu gemessen werden.
			with checkpoint:
				checkpoint.execute("INSERT INTO tiles VALUES (?,?,?,?)",
					(tid,street_sha,grm_sha,json.dumps(contributions,
						separators=(",",":"),allow_nan=False)))
			if tile_number == 1 or tile_number % 50 == 0 or tile_number == tile_count:
				elapsed = monotonic() - started
				eta = elapsed / tile_number * (tile_count - tile_number)
				print(f"SIS V2 measure {tile_number}/{tile_count} "
					f"({100 * tile_number / tile_count:.1f} %) {tid} "
					f"| Laufzeit {_duration(elapsed)} | ETA {_duration(eta)}",
					flush=True)
		if len(groups) != balance["geometrisch_eindeutige_gip_ids"]:
			raise ValueError("GIP-Abschnittsanzahl inkonsistent")
		if abs(sum(v["area"] for v in groups.values())-
			balance["abschnitte_m2"]) > max(.05,balance["abschnitte_m2"]*1e-6):
			raise ValueError("GIP-Flächenbilanz inkonsistent")
		total_area = sum(item["area"] for item in groups.values())
		total_vegetation = sum(item["vegetation"] for item in groups.values())
		total_crown = sum(item["crown"] for item in groups.values())
		grm_fingerprint = None
		if grm_root is not None:
			entries = list(checkpoint.execute(
				"SELECT tile_id,grm_sha FROM tiles ORDER BY tile_id"))
			if len(entries) != len(manifest["tiles"]):
				raise ValueError("GRM-Messcheckpoint nicht vollständig")
			grm_fingerprint = hashlib.sha256(json.dumps(entries,
				separators=(",",":")).encode()).hexdigest()
		stage.mkdir(parents=True)
		try:
			with (stage/"gip_abschnitte.csv").open("w",newline="",encoding="utf-8") as target, \
				(stage/"gip_abschnitte.geojson").open("w",encoding="utf-8") as geo:
				writer = csv.DictWriter(target,fieldnames=FIELDS)
				writer.writeheader()
				geo.write('{"type":"FeatureCollection","features":[')
				for idx,(gid,item) in enumerate(sorted(groups.items())):
					area = item["area"]
					name,fow = axes[gid]
					row = {"gip_id":gid, "strassenname":name, "fow":fow,
						"abschnitt_flaeche_m2":area,
						"boden_m2":item["vegetation"],
						"boden_pct":100*item["vegetation"]/area,
						"nicht_begruent_m2":max(0.,area-item["vegetation"]),
						"nicht_begruent_pct":100*max(0.,area-item["vegetation"])/area,
						"grm_kronen_m2":item["crown"] if grm_root is not None else None,
						"grm_kronen_pct":100*item["crown"]/area if grm_root is not None else None,
						"kachelteile":item["parts"],
						"original_gip_ids":";".join(member_ids[gid]) if grouping else gid}
					writer.writerow(row)
					merged = union_all(item["geometries"])
					if not merged.is_valid or abs(merged.area-area) > max(.05,area*1e-6):
						raise ValueError(f"{gid}: GIP-Ausgabegeometrie inkonsistent")
					feature = {"type":"Feature","id":gid,"properties":row,
						"geometry":mapping(transform(TO_WGS,merged))}
					if idx:
						geo.write(",")
					geo.write(json.dumps(feature,ensure_ascii=False,allow_nan=False))
				geo.write("]}\n")
			report = {"provider":VERSION, "manifest_sha256":manifest_sha,
				"sis_source_sha256":meta["sha256"],"sis_index_sha256":checksum(sis_path),
				"gip_sha256":gip_sha,"partition_sha256":partition_sha,
				"grm_available":grm_root is not None,
				"grm_masks_sha256":grm_fingerprint,"gip_ids":len(groups),
				"strassenraum_m2":balance["strassenraum_m2"],
				"abschnittsflaeche_m2":balance["abschnitte_m2"],
				"ungeklaert_m2":balance["ungeklaert_m2"],
				"ungeklaert_pct":100*balance["ungeklaert_m2"]/balance["strassenraum_m2"],
				"bilanzdifferenz_m2":balance["bilanzdifferenz_m2"],
				"boden_m2":total_vegetation,
				"boden_pct":100*total_vegetation/total_area,
				"nicht_begruent_m2":max(0.,total_area-total_vegetation),
				"nicht_begruent_pct":100*max(0.,total_area-total_vegetation)/total_area,
				"grm_kronen_m2":total_crown if grm_root is not None else None,
				"grm_kronen_pct":100*total_crown/total_area if grm_root is not None else None,
				"darstellungsreferenz_pct":{"boden":40,"grm_kronen":60},
				"boden_belag_codes":sorted(VEGETATION),
				"boden_ueberlagerungsregel":"BL/ST/WI nur außerhalb aller übrigen BELAG-Flächen begrünt; Konfliktflächen konservativ nicht begrünt",
				"klassifikation":"SIS BELAG BL/ST/WI = begrünt; alle anderen BELAG = nicht begrünt; alle TYPE einschließlich M1/M2 enthalten",
				"kreuzungen":config["junction_policy"],
				"gip_kantenvereinigung": ("parallel-gip-groups-v1" if grouping
					else "keine"),
				"gip_quellkanten_gesamt": (sum(len(v) for v in member_ids.values())
					if grouping else len(axes)),
				"gip_vereinigte_gruppen": (sum(len(v)>1 for v in member_ids.values())
					if grouping else 0),
				"geojson_sha256":checksum(stage/"gip_abschnitte.geojson"),
				"csv_sha256":checksum(stage/"gip_abschnitte.csv")}
			(stage/"bericht.json").write_text(json.dumps(report,ensure_ascii=False,
				indent=2)+"\n",encoding="utf-8")
			stage.replace(out_dir)
		except BaseException:
			shutil.rmtree(stage)
			raise
		return report


def main():
	p = argparse.ArgumentParser(description=__doc__)
	for name in ("manifest","gip-index","sis-db","street-root","partition-db","out-dir"):
		p.add_argument("--"+name,required=True,type=Path)
	p.add_argument("--grm-root",type=Path)
	p.add_argument("--grm-raw-root",type=Path)
	p.add_argument("--resume",action="store_true",
		help="Vorhandene fertige Messergebnisse bei identischer Provenienz übernehmen")
	a = vars(p.parse_args())
	print(json.dumps(run(a["manifest"],a["gip_index"],a["sis_db"],
		a["street_root"],a["partition_db"],a["out_dir"],a["grm_root"],
		a["grm_raw_root"],resume=a["resume"]),
		ensure_ascii=False,indent=2))


if __name__ == "__main__":
	main()
