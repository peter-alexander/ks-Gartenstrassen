"""Abschnittsbezogene SIS-V2-Messung mit GIP-Flächen und optional GRM2023.

Bodenklassen sind explizite, vorläufige Arbeitsdefinitionen; getrennt werden
Vegetation und (weiter gefasste) potenziell unversiegelte Beläge ausgewiesen.
Keine FMZK-/Kataster-Abhängigkeiten, keine stillen NULL->0-Umwandlungen.
"""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import shutil
import sqlite3

from pyproj import Transformer
from shapely import union_all
from shapely.geometry import box, mapping
from shapely.ops import transform
from shapely.wkb import loads

from scripts.sis_v2_street import VERSION
from scripts.wienwide_grid import checksum, read_manifest
from scripts.wienwide_partition import report_results
from scripts.wienwide_gip import connect as connect_gip
from scripts.wienwide_grm2023 import read_mask as read_grm

TO_WGS = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform
VEGETATION = frozenset(("BL", "ST", "WI"))
POTENTIALLY_UNSEALED = frozenset(("BL", "ST", "WI", "KB", "MW", "GO"))
FIELDS = ("gip_id", "strassenname", "fow", "abschnitt_flaeche_m2",
	"sis_vegetation_m2", "sis_vegetation_pct", "sis_potentiell_unversiegelt_m2",
	"sis_potentiell_unversiegelt_pct", "grm_kronen_m2", "grm_kronen_pct", "kachelteile")


def _mask(db, core, categories):
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


def _intersect_area(part, mask):
	return part.intersection(mask).area if mask is not None else 0.


def run(manifest_path, gip_path, sis_path, street_root, partition_path,
		out_dir, grm_root=None):
	manifest, aoi = read_manifest(manifest_path)
	out_dir, sis_path = Path(out_dir), Path(sis_path)
	if out_dir.exists():
		raise FileExistsError(out_dir)
	stage = out_dir.with_name(out_dir.name + ".tmp")
	if stage.exists():
		raise FileExistsError(stage)
	with sqlite3.connect(f"file:{sis_path.resolve()}?mode=ro", uri=True) as sis, \
			sqlite3.connect(f"file:{Path(partition_path).resolve()}?mode=ro", uri=True) as partition, \
			connect_gip(gip_path) as gip:
		meta = dict(sis.execute("SELECT key,value FROM metadata"))
		if meta.get("crs") != "EPSG:31256" or meta.get("provider") != "SISBELAGOGD":
			raise ValueError("Ungültiger SIS-Index")
		config = dict(partition.execute("SELECT key,value FROM config"))
		expected = {"schema_version":"1", "manifest_sha256":checksum(manifest_path),
			"gip_sha256":checksum(gip_path)}
		if config != {**expected,"junction_policy":"none"}:
			raise ValueError("SIS V2 benötigt die Voronoi-Partition ohne Kreuzungsabzug")
		balance = report_results(partition,manifest)
		axes = {str(gid):(name,fow) for gid,name,fow in gip.execute(
			"SELECT gip,name,fow FROM axes")}
		groups = defaultdict(lambda:{"area":0.,"vegetation":0.,"unsealed":0.,
			"crown":0.,"parts":0,"geometries":[]})
		for tile in manifest["tiles"]:
			tid = tile["id"]
			core = box(*tile["bounds_31256"]).intersection(aoi)
			street_path = Path(street_root)/tid/"street.sqlite"
			with sqlite3.connect(f"file:{street_path.resolve()}?mode=ro", uri=True) as street:
				street_meta = dict(street.execute("SELECT key,value FROM metadata"))
				if (street_meta.get("strassenraum_regel_version") != VERSION
					or street_meta.get("sis_sha256") != meta["sha256"]
					or street_meta.get("manifest_sha256") != checksum(manifest_path)):
					raise ValueError(f"{tid}: unerwartete Straßenraumquelle")
				street_geom = loads(street.execute("SELECT geom FROM street").fetchone()[0])
				if not street_geom.is_valid or street_geom.difference(core).area > .01:
					raise ValueError(f"{tid}: Straßenraum ungültig")
			psha = partition.execute("SELECT street_sha256 FROM tiles WHERE id=?",
				(tid,)).fetchone()
			if psha is None or psha[0] != checksum(street_path):
				raise ValueError(f"{tid}: Partition für andere Straßenraumkachel")
			vegetation = _mask(sis,core,VEGETATION)
			unsealed = _mask(sis,core,POTENTIALLY_UNSEALED)
			crown = None
			if grm_root is not None:
				crown, _ = read_grm(grm_root,tile,manifest=manifest_path,aoi=aoi)
			for gid,stored_area,blob in partition.execute(
				"SELECT gip_id,area,geom FROM parts WHERE tile_id=? AND kind='abschnitt'", (tid,)):
				gid = str(gid)
				if gid not in axes or axes[gid][1] != 3:
					raise ValueError(f"{tid}/{gid}: GIP-Achse fehlt oder FOW != 3")
				part = loads(blob)
				if (not part.is_valid or part.is_empty or
					abs(part.area-stored_area) > max(.01,stored_area*1e-8) or
					part.difference(street_geom).area > .01):
					raise ValueError(f"{tid}/{gid}: Geometrie nicht in SIS-Straßenraum")
				v = _intersect_area(part,vegetation)
				u = _intersect_area(part,unsealed)
				c = _intersect_area(part,crown) if crown is not None else 0.
				if max(v,u,c) > stored_area + .01:
					raise ValueError(f"{tid}/{gid}: Belags-/Kronenfläche zu groß")
				item = groups[gid]
				item["area"] += stored_area
				item["vegetation"] += v
				item["unsealed"] += u
				item["crown"] += c
				item["parts"] += 1
				item["geometries"].append(part)
		if len(groups) != balance["geometrisch_eindeutige_gip_ids"]:
			raise ValueError("GIP-Abschnittsanzahl inkonsistent")
		if abs(sum(v["area"] for v in groups.values())-
			balance["abschnitte_m2"]) > max(.05,balance["abschnitte_m2"]*1e-6):
			raise ValueError("GIP-Flächenbilanz inkonsistent")
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
						"sis_vegetation_m2":item["vegetation"],
						"sis_vegetation_pct":100*item["vegetation"]/area,
						"sis_potentiell_unversiegelt_m2":item["unsealed"],
						"sis_potentiell_unversiegelt_pct":100*item["unsealed"]/area,
						"grm_kronen_m2":item["crown"] if grm_root is not None else None,
						"grm_kronen_pct":100*item["crown"]/area if grm_root is not None else None,
						"kachelteile":item["parts"]}
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
			report = {"provider":VERSION, "manifest_sha256":checksum(manifest_path),
				"sis_source_sha256":meta["sha256"],"sis_index_sha256":checksum(sis_path),
				"gip_sha256":checksum(gip_path),"partition_sha256":checksum(partition_path),
				"grm_available":grm_root is not None,"gip_ids":len(groups),
				"strassenraum_m2":balance["strassenraum_m2"],
				"abschnittsflaeche_m2":balance["abschnitte_m2"],
				"ungeklaert_m2":balance["ungeklaert_m2"],
				"vegetations_belag_codes":sorted(VEGETATION),
				"potentiell_unversiegelt_belag_codes":sorted(POTENTIALLY_UNSEALED),
				"warnung":"BELAG-Zuordnung vorläufig; potenziell unversiegelt bedeutet nicht nachgewiesen entsiegelt. Keine Kreuzungs-Neuabgrenzung."}
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
	a = vars(p.parse_args())
	print(json.dumps(run(a["manifest"],a["gip_index"],a["sis_db"],
		a["street_root"],a["partition_db"],a["out_dir"],a["grm_root"]),
		ensure_ascii=False,indent=2))


if __name__ == "__main__":
	main()
