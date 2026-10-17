"""SIS-V2-Straßenraumkacheln aus bereits geprüftem Pilot-Index erzeugen.

Keine FMZK-/Kataster-Eingaben. Raster und AOI stammen aus einem separaten
GIP/GRM-Manifest für den Pilot; V0-Verzeichnisse niemals wiederverwenden.
"""
import argparse
import json
from pathlib import Path
import sqlite3

from shapely.geometry import box
from shapely.wkb import loads

from scripts.sis_belagsflaechen import SCHEMA as SIS_SCHEMA
from scripts.wienwide_grid import read_manifest, checksum
from scripts.wienwide_street import save_street_tile, load_street_tile

VERSION = "sis-belagsflaechen-v2"


def run(manifest_path, sis_db, out_root):
	manifest, aoi = read_manifest(manifest_path)
	out_root, sis_db = Path(out_root), Path(sis_db)
	with sqlite3.connect(f"file:{sis_db.resolve()}?mode=ro", uri=True) as db:
		metadata = dict(db.execute("SELECT key,value FROM metadata"))
		if metadata.get("schema") != SIS_SCHEMA or metadata.get("crs") != "EPSG:31256":
			raise ValueError("Unpassender SIS-Pilotindex")
		source = sis_db.parent/"SISBELAGOGD.json"
		if checksum(source) != metadata.get("sha256"):
			raise ValueError("SIS-Quelldatei stimmt nicht mit Index überein")
		row = db.execute("SELECT geom FROM street").fetchone()
		if row is None:
			raise ValueError("SIS-Union fehlt")
		union = loads(row[0])
		if union.is_empty or not union.is_valid:
			raise ValueError("Ungültige SIS-Union")
		results = []
		for tile in manifest["tiles"]:
			core = box(*tile["bounds_31256"]).intersection(aoi)
			clipped = union.intersection(core)
			if not clipped.is_valid or clipped.difference(core).area > .01:
				raise ValueError(f"{tile['id']}: ungültiger SIS-Schnitt")
			path = out_root/tile["id"]/"street.sqlite"
			meta = {"schema_version": "1", "crs": "EPSG:31256",
				"tile_id": tile["id"], "strassenraum_regel_version": VERSION,
				"sis_sha256": metadata["sha256"],
				"sis_index_sha256": checksum(sis_db),
				"manifest_sha256": checksum(manifest_path),
				"strassenraum_m2": repr(clipped.area)}
			if path.exists():
				with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as previous:
					old = dict(previous.execute("SELECT key,value FROM metadata"))
				if old != meta:
					raise ValueError(f"{tile['id']}: SIS-Kachelcache aus anderen Eingaben")
				stored = load_street_tile(path, core)
				if stored.symmetric_difference(clipped).area > .01:
					raise ValueError(f"{tile['id']}: SIS-Kachelgeometrie abweichend")
			else:
				save_street_tile(path, clipped, meta, allow_empty=True)
			results.append({"tile": tile["id"], "area_m2": clipped.area})
	return {"provider": VERSION, "kacheln": len(results),
		"strassenraum_m2": sum(r["area_m2"] for r in results),
		"sis_sha256": metadata["sha256"]}


def main():
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("--manifest", required=True, type=Path)
	p.add_argument("--sis-db", required=True, type=Path)
	p.add_argument("--out-root", required=True, type=Path)
	args = p.parse_args()
	print(json.dumps(run(args.manifest, args.sis_db, args.out_root),
		ensure_ascii=False, indent=2))


if __name__ == "__main__":
	main()
