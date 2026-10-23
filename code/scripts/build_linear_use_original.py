"""Read untouched LINEAR_USE selected base_type linework for the Vienna CGAL pipeline.

Only CRS conversion to EPSG:31256 is performed. Each original object_id
remains a separate segment source with its own edge_id. No mean axes.
"""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from pyproj import Transformer
from shapely.geometry import mapping
from shapely.ops import transform
from shapely.wkb import dumps

from scripts.linear_use_source import (
	_readonly, _gpkg_wkb, _require_columns, _source_geometry_info, _source_rows, BASE_TYPES)
from scripts.wienwide_grid import checksum, load_aoi

SCHEMA="linear-use-original-segments-v2"


def build(source,aoi_path,output_db,geojson):
	source,aoi_path,output_db,geojson=map(Path,(source,aoi_path,output_db,geojson))
	for path in (output_db,geojson):
		if path.exists() or path.is_symlink():
			raise FileExistsError(path)
	aoi=load_aoi(aoi_path)
	source_sha=checksum(source)
	aoi_sha=checksum(aoi_path)
	records=[]
	with _readonly(source) as db:
		_require_columns(db)
		geom_column,source_crs=_source_geometry_info(db)
		to_metric=Transformer.from_crs(source_crs,31256,always_xy=True).transform
		from_metric=Transformer.from_crs(31256,source_crs,always_xy=True).transform
		source_bounds=transform(from_metric,aoi).bounds
		rows,used_rtree=_source_rows(db,geom_column,source_bounds)
		for object_id,edge_id,_pct_from,_pct_to,_base_type,_length,_name,blob in rows:
			object_id=str(object_id or "").strip()
			edge_id=str(edge_id or "").strip()
			if not object_id or not edge_id:
				raise ValueError("LINEAR_USE: object_id oder edge_id fehlt")
			geometry=_gpkg_wkb(blob)
			if geometry.geom_type!="LineString" or geometry.is_empty or not geometry.is_valid or geometry.length<=0:
				raise ValueError(f"LINEAR_USE {object_id}: gültiger LineString erforderlich")
			metric=transform(to_metric,geometry)
			if metric.is_empty or not metric.is_valid or metric.length<=0:
				raise ValueError(f"LINEAR_USE {object_id}: ungültige Projektion")
			if metric.intersects(aoi):
				records.append((edge_id,object_id,int(_base_type),metric))
	if not records:
		raise ValueError("Keine LINEAR_USE-Geometrien der ausgewählten base_types in Wien")
	records.sort(key=lambda row:(row[0],row[1]))
	if len({r[1] for r in records})!=len(records):
		raise ValueError("LINEAR_USE: object_id nicht eindeutig")
	output_db.parent.mkdir(parents=True,exist_ok=True)
	geojson.parent.mkdir(parents=True,exist_ok=True)
	if output_db.with_name(output_db.name+".tmp").exists():
		raise FileExistsError(output_db.with_name(output_db.name+".tmp"))
	temp_db=output_db.with_name(output_db.name+".tmp")
	temp_json=None
	try:
		with sqlite3.connect(temp_db) as db:
			db.executescript("""
				CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
				CREATE TABLE linear_use_segments(
					object_id TEXT PRIMARY KEY,edge_id TEXT NOT NULL,base_type INTEGER NOT NULL,wkb BLOB NOT NULL);
				CREATE INDEX linear_use_segments_edge ON linear_use_segments(edge_id);
			""")
			db.executemany("INSERT INTO linear_use_segments VALUES (?,?,?,?)",
				[(object_id,edge_id,base_type,dumps(geom)) for edge_id,object_id,base_type,geom in records])
			db.executemany("INSERT INTO metadata VALUES (?,?)",[
				("schema",json.dumps(SCHEMA)),
				("base_types",json.dumps(BASE_TYPES)),
				("target_crs",json.dumps("EPSG:31256")),
				("source_sha256",json.dumps(source_sha)),
				("aoi_sha256",json.dumps(aoi_sha))])
		to_wgs=Transformer.from_crs(31256,4326,always_xy=True).transform
		with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",
				dir=geojson.parent,prefix=".linear-use-original-",suffix=".tmp",
				delete=False) as out:
			temp_json=Path(out.name)
			out.write('{"type":"FeatureCollection","features":[')
			for i,(edge_id,object_id,base_type,geom) in enumerate(records):
				if i:
					out.write(",\n")
				out.write(json.dumps({"type":"Feature",
					"properties":{"edge_id":edge_id,"object_id":object_id,"base_type":base_type},
					"geometry":mapping(transform(to_wgs,geom))},
					ensure_ascii=False,separators=(",",":"),allow_nan=False))
			out.write("]}\n")
		os.replace(temp_db,output_db)
		os.replace(temp_json,geojson)
		temp_json=None
	except BaseException:
		temp_db.unlink(missing_ok=True)
		if temp_json is not None:
			temp_json.unlink(missing_ok=True)
		raise
	return {"schema":SCHEMA,"original_lines":len(records),
		"edge_ids":len({r[0] for r in records}),
		"spatial_prefilter":"gpkg_rtree" if used_rtree else "table_scan"}


def main():
	parser=argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--source",type=Path,required=True)
	parser.add_argument("--aoi",type=Path,required=True)
	parser.add_argument("--out",type=Path,required=True)
	parser.add_argument("--geojson",type=Path,required=True)
	args=parser.parse_args()
	print(json.dumps(build(args.source,args.aoi,args.out,args.geojson),
		ensure_ascii=False))


if __name__=="__main__":
	main()
