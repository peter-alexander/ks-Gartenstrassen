"""WGS84 GeoJSON of ALL GIP axes immediately after parallel-edge grouping.

One feature per remaining representative, including unmerged originals.
For merged axes the geometry contains every original GIP line as a MultiLineString;
no invented centreline, no Voronoi result, no dependency on SIS/GRM.
The separately attested output is a diagnostic and does not modify the
already released SIS/GRM GeoJSON, PMTiles or freigabe.json.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from pyproj import Transformer
from shapely.geometry import mapping
from shapely.ops import transform
from shapely.wkb import loads

from scripts.wienwide_grid import checksum

SCHEMA = "gartenstrassen-gip-merge-geojson-v1"
FILE = "gip_kanten_vereinigt.geojson"
META = "gip_kanten_vereinigt.meta.json"
TO_WGS = Transformer.from_crs("EPSG:31256","EPSG:4326",
	always_xy=True).transform


def _metadata(db):
	meta={key:json.loads(value) for key,value in db.execute(
		"SELECT key,value FROM meta")}
	if (meta.get("graph_groups_schema")!="parallel-gip-groups-v1"
		or meta.get("index_method")!="gip2-local-edge-turn-use-v1"
		or meta.get("sampling_m")!=5
		or meta.get("crs")!="EPSG:31256"):
		raise ValueError("Kein gültiger vereinigter GIP2-Index (EPSG:31256, 5-m-Sites)")
	for table in ("original_axes","merged_members","merged_groups"):
		if db.execute("SELECT 1 FROM sqlite_master WHERE name=?",
				(table,)).fetchone() is None:
			raise ValueError(f"Originalzuordnung fehlt in GIP-Index: {table}")
	return meta


def export(index,output_dir):
	index,output_dir=Path(index),Path(output_dir)
	if not index.is_file() or index.is_symlink():
		raise FileNotFoundError(f"Abgeleiteter GIP-Graph fehlt: {index}")
	if output_dir.is_symlink():
		raise ValueError("Output darf kein Symlink sein")
	output_dir.mkdir(parents=True,exist_ok=True)
	output=output_dir/FILE
	attestation=output_dir/META
	if output.is_symlink() or attestation.is_symlink():
		raise ValueError("GeoJSON-Ausgabe darf kein Symlink sein")
	# Full index hash distinguishes changed group memberships and site owners.
	index_sha=checksum(index)
	if output.is_file() and attestation.is_file():
		try:
			previous=json.loads(attestation.read_text(encoding="utf-8"))
		except (json.JSONDecodeError,UnicodeError):
			previous={}
		if (previous.get("schema")==SCHEMA
			and previous.get("gip_merged_sha256")==index_sha
			and previous.get("geojson_sha256")==checksum(output)):
			print(f"GIP-Kantenexport: gültigen Bestand wiederverwendet: {output}",
				flush=True)
			return previous
		# Refuse stale or corrupt output: no implicit overwriting of
		# an independently inspected prior grouping.
		raise ValueError(f"{output}: vorhandener Export für andere GIP-Gruppen. "
			"Bitte gesondert sichern und aus dem aktiven Ausgabepfad entfernen.")
	if output.exists() or attestation.exists():
		raise FileExistsError("Unvollständiger vorhandener GIP-Kantenexport: "
			"beide Dateien vor einer erneuten Ausgabe separat aufbewahren")
	stage=None
	try:
		with sqlite3.connect(f"file:{index.resolve()}?mode=ro",uri=True) as db:
			meta=_metadata(db)
			if db.execute("PRAGMA quick_check").fetchone()[0]!="ok":
				raise ValueError("Vereinigte GIP-SQLite ist beschädigt")
			members={}
			for original,representative,role,fow in db.execute(
					"SELECT original_id,representative_id,role,original_fow "
					"FROM merged_members ORDER BY representative_id,original_id"):
				members.setdefault(representative,[]).append((original,role,fow))
			expected=db.execute("SELECT COUNT(*) FROM axes").fetchone()[0]
			source_count=db.execute("SELECT COUNT(*) FROM original_axes").fetchone()[0]
			if len(members)!=expected or sum(map(len,members.values()))!=source_count:
				raise ValueError("Vereinigungsgruppen entsprechen nicht vollständig den Original-IDs")
			if meta.get("achsen")!=expected or meta.get("original_axes")!=source_count:
				raise ValueError("GIP-Graph-Metadaten widersprechen den gespeicherten Kanten")
			with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",
					dir=output_dir,prefix=FILE+".",suffix=".tmp",
					delete=False) as temp:
				stage=Path(temp.name)
				temp.write('{"type":"FeatureCollection","features":[')
				count=0
				merged_count=0
				for gid,name,fow,blob in db.execute(
						"SELECT gip,name,fow,wkb FROM axes ORDER BY gip"):
					refs=members.get(gid)
					if refs is None:
						raise ValueError(f"Fehlende Original-IDs für Achse {gid}")
					geometry=loads(blob)
					if geometry.is_empty or geometry.geom_type not in (
							"LineString","MultiLineString"):
						raise ValueError(f"Ungültige GIP-Linie {gid}")
					wgs=transform(TO_WGS,geometry)
					if wgs.is_empty or not wgs.is_valid:
						raise ValueError(f"GIP-Linie {gid} nicht nach WGS84 transformierbar")
					props={
						"gip_id":gid,
						"strassenname":name,
						"fow":fow,
						"vereint":len(refs)>1,
						"anzahl_originalkanten":len(refs),
						"original_gip_ids":[r[0] for r in refs],
						"original_fow":[r[2] for r in refs],
						"laenge_m":geometry.length,
					}
					feature={"type":"Feature","id":gid,
						"properties":props,"geometry":mapping(wgs)}
					if count:
						temp.write(",\n")
					temp.write(json.dumps(feature,ensure_ascii=False,
						separators=(",",":"),allow_nan=False))
					count+=1
					merged_count+=len(refs)>1
				temp.write(']}\n')
			if count!=expected or merged_count!=meta.get("merged_groups"):
				raise ValueError("Exportierte Kanten entsprechen nicht der GIP-Vereinigung")
		info={
			"schema":SCHEMA,
			"gip_merged_sha256":index_sha,
			"gip_quellindex_sha256":meta["source_index_sha256"],
			"geojson_sha256":checksum(stage),
			"crs":"EPSG:4326",
			"achsen_gesamt":count,
			"vereinigte_gruppen":merged_count,
			"originalkanten_gesamt":source_count,
			"voronoi_sites":meta["voronoi_sites"],
			"geojson":FILE,
		}
		# Commit the data, then its provenance marker. Interrupted exports are
		# visibly incomplete and never silently accepted as a valid cache.
		os.replace(stage,output)
		stage=None
		with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",
				dir=output_dir,prefix=META+".",suffix=".tmp",
				delete=False) as temp:
			meta_stage=Path(temp.name)
			json.dump(info,temp,ensure_ascii=False,indent=2)
			temp.write("\n")
		try:
			os.replace(meta_stage,attestation)
		finally:
			meta_stage.unlink(missing_ok=True)
		print(f"GIP-Kantenexport: {count} Achsen, {merged_count} vereinigte "
			f"Gruppen, {source_count} ursprüngliche Kanten: {output}",flush=True)
		return info
	finally:
		if stage is not None:
			stage.unlink(missing_ok=True)


def main():
	parser=argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--gip-index",type=Path,required=True)
	parser.add_argument("--output-dir",type=Path,required=True)
	args=parser.parse_args()
	print(json.dumps(export(args.gip_index,args.output_dir),
		ensure_ascii=False,indent=2))


if __name__=="__main__":
	main()
