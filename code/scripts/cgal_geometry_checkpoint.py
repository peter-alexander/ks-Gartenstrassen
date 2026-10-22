"""Reusable validated Voronoi geometry checkpoint before site attribution.

Avoid rerunning multi-million-edge CGAL and polygonize_full when only
the attribution code changes. Cache identity includes raw input data,
CGAL binary and geometry-building Python modules; failures cannot
silently switch to a stale checkpoint.
"""
import json
import os
from pathlib import Path
import sqlite3

from shapely.wkb import dumps, loads

from scripts.wienwide_grid import checksum

SCHEMA="cgal-pre-sis-geometry-checkpoint-v1"


def checkpoint_path(output):
	out=Path(output)
	return out.with_name(out.stem+"__geometry_checkpoint.sqlite")


def identity(cache,aoi,binary):
	root=Path(__file__).resolve().parent
	return {
		"schema":SCHEMA,
		"original_linear_use_sha256":checksum(cache),
		"aoi_sha256":checksum(aoi),
		"cgal_binary_sha256":checksum(binary),
		"segment_input_code_sha256":checksum(root/"cgal_segment_input.py"),
		"polygonization_code_sha256":checksum(root/"build_cgal_voronoi_geojson.py"),
	}


def save_checkpoint(path,expected,polygons,sites,site_stats,
		dual_stats,topology,source_segment_count):
	path=Path(path)
	if path.exists() or path.is_symlink():
		raise FileExistsError(path)
	path.parent.mkdir(parents=True,exist_ok=True)
	temp=path.with_name("."+path.name+".tmp")
	if temp.exists() or temp.is_symlink():
		raise FileExistsError(temp)
	try:
		with sqlite3.connect(temp) as db:
			db.executescript("""
				CREATE TABLE metadata(
					key TEXT PRIMARY KEY,
					value TEXT NOT NULL
				);
				CREATE TABLE polygons(
					id INTEGER PRIMARY KEY,
					wkb BLOB NOT NULL
				);
				CREATE TABLE segment_sites(
					id INTEGER PRIMARY KEY,
					site_line INTEGER NOT NULL UNIQUE,
					edge_id TEXT NOT NULL,
					wkb BLOB NOT NULL
				);
			""")
			values={
				"identity":expected,
				"site_stats":site_stats,
				"dual_stats":dual_stats,
				"topology":topology,
				"source_segment_count":source_segment_count,
				"polygon_count":len(polygons),
				"site_count":len(sites)}
			db.executemany("INSERT INTO metadata VALUES (?,?)",
				((key,json.dumps(value,ensure_ascii=False))
					for key,value in values.items()))
			db.executemany("INSERT INTO polygons VALUES (?,?)",
				((i,dumps(geom)) for i,geom in enumerate(polygons)))
			db.executemany("INSERT INTO segment_sites VALUES (?,?,?,?)",
				((i,num,owner,dumps(geom)) for i,(num,owner,geom)
					in enumerate(sites)))
		os.replace(temp,path)
	except BaseException:
		temp.unlink(missing_ok=True)
		raise


def load_checkpoint(path,expected):
	path=Path(path)
	with sqlite3.connect(f"file:{path.resolve()}?mode=ro",uri=True) as db:
		data={key:json.loads(value) for key,value
			in db.execute("SELECT key,value FROM metadata")}
		if data["identity"]!=expected:
			difference=sorted(
				key for key in expected
				if expected[key]!=data["identity"].get(key))
			raise ValueError("CGAL-Zwischenspeicher ist veraltet: "
				+", ".join(difference)
				+". Für eine Neuberechnung die alte Datei archivieren.")
		polygons=[loads(wkb) for (wkb,) in db.execute(
			"SELECT wkb FROM polygons ORDER BY id")]
		sites=[(number,owner,loads(wkb))
			for number,owner,wkb in db.execute(
				"SELECT site_line,edge_id,wkb FROM segment_sites ORDER BY id")]
	if len(polygons)!=data["polygon_count"] or len(sites)!=data["site_count"]:
		raise ValueError("CGAL-Zwischenspeicher unvollständig")
	if not polygons or not sites:
		raise ValueError("CGAL-Zwischenspeicher leer")
	return (polygons,sites,data["site_stats"],data["dual_stats"],
		data["topology"],data["source_segment_count"])
