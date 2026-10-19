"""Build one Vienna street-section mean axis per LINEAR_USE edge_id.

Source: LINEAR_USE in gip_network_ogd.gpkg, read-only.
Selection: base_type = 1 only, intersecting the supplied Vienna AOI.
Grouping: edge_id only.
Geometry: one source line stays unchanged; multiple source lines are replaced
by the deterministic sampled arithmetic mean axis from linear_use_centerline.

No MAX_SPEED, EDGE, NODE, TURN_USE, names, widths or geometric proximity are
used to decide membership.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import struct
import tempfile
from urllib.parse import quote

from pyproj import CRS, Transformer
from shapely.geometry import mapping
from shapely.ops import transform
from shapely.wkb import dumps, loads

from scripts.linear_use_centerline import build_mean_axis
from scripts.wienwide_grid import checksum, load_aoi

SCHEMA="linear-use-edge-mean-axis-v1"
BASE_TYPE=1
TARGET_CRS="EPSG:31256"
WGS84="EPSG:4326"


def _readonly(path):
	path=Path(path).resolve()
	if not path.is_file():
		raise FileNotFoundError(path)
	return sqlite3.connect(
		"file:"+quote(str(path),safe="/")+"?mode=ro&immutable=1",uri=True)


def _gpkg_wkb(blob):
	if blob is None:
		raise ValueError("LINEAR_USE-Geometrie fehlt")
	data=bytes(blob)
	if len(data)<8 or data[:2]!=b"GP":
		raise ValueError("Ungültiger GeoPackage-Geometrieheader")
	flags=data[3]
	envelope=(flags>>1)&7
	if envelope>4:
		raise ValueError("Unbekannter GeoPackage-Envelope")
	offset=8+(0,32,48,48,64)[envelope]
	if len(data)<=offset:
		raise ValueError("GeoPackage-Geometrie ist abgeschnitten")
	return loads(data[offset:])


def _source_geometry_info(db):
	row=db.execute("""
		SELECT column_name,geometry_type_name,srs_id
		FROM gpkg_geometry_columns
		WHERE table_name='LINEAR_USE'
	""").fetchone()
	if row is None:
		raise ValueError("GeoPackage enthält keinen registrierten LINEAR_USE-Layer")
	column,geometry_type,srs_id=row
	if str(geometry_type).upper() not in ("LINESTRING","GEOMETRY"):
		raise ValueError(
			f"LINEAR_USE: unerwarteter registrierter Geometrietyp {geometry_type}")
	srs=db.execute("""
		SELECT organization,organization_coordsys_id
		FROM gpkg_spatial_ref_sys WHERE srs_id=?
	""",(srs_id,)).fetchone()
	if srs is None:
		raise ValueError(f"LINEAR_USE: unbekanntes srs_id {srs_id}")
	organization,code=srs
	try:
		crs=CRS.from_user_input(f"{organization}:{code}")
	except Exception as exc:
		raise ValueError(
			f"LINEAR_USE: CRS {organization}:{code} nicht lesbar") from exc
	return str(column),crs


def _columns(db):
	return {row[1] for row in db.execute("PRAGMA table_info('LINEAR_USE')")}


def _require_columns(db):
	required={
		"object_id","edge_id","edge_percentage_from","edge_percentage_to",
		"base_type","length_m","feature_name",
	}
	missing=required-_columns(db)
	if missing:
		raise ValueError(
			"LINEAR_USE: Pflichtspalten fehlen: "+", ".join(sorted(missing)))


def _pk_column(db):
	for row in db.execute("PRAGMA table_info('LINEAR_USE')"):
		if row[5]:
			return row[1]
	raise ValueError("LINEAR_USE: Primärschlüssel für räumlichen Index fehlt")


def _source_rows(db,geom_column,source_aoi_bounds):
	pk=_pk_column(db)
	rtree=f"rtree_LINEAR_USE_{geom_column}"
	has_rtree=db.execute(
		"SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
		(rtree,)).fetchone() is not None
	if has_rtree:
		minx,miny,maxx,maxy=source_aoi_bounds
		query=f"""
			SELECT l.object_id,l.edge_id,l.edge_percentage_from,
				l.edge_percentage_to,l.base_type,l.length_m,l.feature_name,
				l."{geom_column}"
			FROM LINEAR_USE l
			JOIN "{rtree}" r ON r.id=l."{pk}"
			WHERE l.base_type=?
				AND r.maxx>=? AND r.minx<=?
				AND r.maxy>=? AND r.miny<=?
			ORDER BY l.edge_id,l.object_id
		"""
		return db.execute(query,(BASE_TYPE,minx,maxx,miny,maxy)),True
	query=f"""
		SELECT object_id,edge_id,edge_percentage_from,edge_percentage_to,
			base_type,length_m,feature_name,"{geom_column}"
		FROM LINEAR_USE
		WHERE base_type=?
		ORDER BY edge_id,object_id
	"""
	return db.execute(query,(BASE_TYPE,)),False


def _json_list(values):
	return json.dumps(list(values),ensure_ascii=False,separators=(",",":"))


def _atomic_geojson(path,features):
	path=Path(path)
	path.parent.mkdir(parents=True,exist_ok=True)
	stage=None
	try:
		with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",
				dir=path.parent,prefix=path.name+".",suffix=".tmp",
				delete=False) as out:
			stage=Path(out.name)
			json.dump({"type":"FeatureCollection","features":features},out,
				ensure_ascii=False,separators=(",",":"),allow_nan=False)
			out.write("\n")
		os.replace(stage,path)
		stage=None
	finally:
		if stage is not None:
			stage.unlink(missing_ok=True)


def _write_geojson(path,axes):
	path=Path(path)
	if path.exists() or path.is_symlink():
		raise FileExistsError(path)
	path.parent.mkdir(parents=True,exist_ok=True)
	stage=None
	to_wgs=Transformer.from_crs(TARGET_CRS,WGS84,always_xy=True).transform
	try:
		with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",
				dir=path.parent,prefix=path.name+".",suffix=".tmp",
				delete=False) as out:
			stage=Path(out.name)
			out.write('{"type":"FeatureCollection","features":[')
			for number,item in enumerate(axes):
				if number:
					out.write(",\n")
				geometry=transform(to_wgs,item["geometry"])
				feature={
					"type":"Feature",
					"id":item["edge_id"],
					"properties":{
						"edge_id":item["edge_id"],
						"linear_use_count":item["source_count"],
						"linear_use_object_ids":item["object_ids"],
						"feature_names":item["feature_names"],
						"geometry_method":item["audit"].method,
						"endpoint_snap_max_m":item["audit"].endpoint_snap_max_m,
						"mean_axis_length_m":item["geometry"].length,
						"source_length_min_m":item["audit"].min_length_m,
						"source_length_max_m":item["audit"].max_length_m,
						"length_ratio_min_max":item["audit"].length_ratio_min_max,
						"max_correspondence_spread_m":
							item["audit"].max_correspondence_spread_m,
						"mean_correspondence_spread_m":
							item["audit"].mean_correspondence_spread_m,
					},
					"geometry":mapping(geometry),
				}
				out.write(json.dumps(feature,ensure_ascii=False,
					separators=(",",":"),allow_nan=False))
			out.write("]}\n")
		os.replace(stage,path)
		stage=None
	finally:
		if stage is not None:
			stage.unlink(missing_ok=True)


def build(source,aoi_path,output_db,geojson,*,sample_spacing_m=5.0):
	source,aoi_path,output_db,geojson=map(Path,
		(source,aoi_path,output_db,geojson))
	if output_db.exists() or output_db.is_symlink():
		raise FileExistsError(output_db)
	if geojson.exists() or geojson.is_symlink():
		raise FileExistsError(geojson)
	aoi=load_aoi(aoi_path)
	source_sha=checksum(source)
	aoi_sha=checksum(aoi_path)
	temp=output_db.with_name(output_db.name+".tmp")
	if temp.exists() or temp.is_symlink():
		raise FileExistsError(temp)
	output_db.parent.mkdir(parents=True,exist_ok=True)
	groups={}
	members=[]
	try:
		with _readonly(source) as src:
			_require_columns(src)
			geom_column,source_crs=_source_geometry_info(src)
			to_metric=Transformer.from_crs(
				source_crs,TARGET_CRS,always_xy=True).transform
			from_metric=Transformer.from_crs(
				TARGET_CRS,source_crs,always_xy=True).transform
			source_aoi=transform(from_metric,aoi)
			total_base_type_1=src.execute(
				"SELECT COUNT(*) FROM LINEAR_USE WHERE base_type=?",
				(BASE_TYPE,)).fetchone()[0]
			rows,used_rtree=_source_rows(
				src,geom_column,source_aoi.bounds)
			candidate_rows=0
			selected_rows=0
			for (object_id,edge_id,pct_from,pct_to,base_type,length_m,
					feature_name,blob) in rows:
				candidate_rows+=1
				object_id=str(object_id or "").strip()
				edge_id=str(edge_id or "").strip()
				if not object_id:
					raise ValueError("LINEAR_USE base_type=1 ohne object_id")
				if not edge_id:
					raise ValueError(
						f"LINEAR_USE {object_id}: edge_id fehlt")
				geometry=_gpkg_wkb(blob)
				if geometry.geom_type!="LineString" or (
						geometry.is_empty or not geometry.is_valid
						or geometry.length<=0):
					raise ValueError(
						f"LINEAR_USE {object_id}: gültiger LineString erwartet")
				metric=transform(to_metric,geometry)
				if metric.is_empty or not metric.is_valid or metric.length<=0:
					raise ValueError(
						f"LINEAR_USE {object_id}: Transformation nach "
						"EPSG:31256 ungültig")
				if not metric.intersects(aoi):
					continue
				selected_rows+=1
				groups.setdefault(edge_id,[]).append((object_id,metric))
				members.append({
					"object_id":object_id,
					"edge_id":edge_id,
					"edge_percentage_from":pct_from,
					"edge_percentage_to":pct_to,
					"length_m":length_m,
					"feature_name":str(feature_name or ""),
					"geometry":metric,
				})
		if not groups:
			raise ValueError(
				"Keine LINEAR_USE base_type=1-Geometrien innerhalb der Wien-AOI")
		axes=[]
		failures=[]
		members_by_edge={}
		for item in members:
			members_by_edge.setdefault(item["edge_id"],[]).append(item)
		for edge_id,items in sorted(groups.items()):
			try:
				axis,audit=build_mean_axis(
					[item[1] for item in items],
					sample_spacing_m=sample_spacing_m)
			except ValueError as exc:
				failures.append((edge_id,len(items),str(exc)))
				continue
			names=sorted({m["feature_name"] for m in members_by_edge[edge_id]
				if m["feature_name"]})
			axes.append({
				"edge_id":edge_id,
				"source_count":len(items),
				"object_ids":[item[0] for item in items],
				"feature_names":names,
				"geometry":axis,
				"audit":audit,
			})
		if failures:
			preview=", ".join(
				f"{edge_id} ({count} Linien: {reason})"
				for edge_id,count,reason in failures[:10])
			more=f"; weitere {len(failures)-10}" if len(failures)>10 else ""
			raise ValueError(
				f"{len(failures)} edge_id-Gruppen erzeugen keine einfache "
				f"Mittelachse: {preview}{more}")
		with sqlite3.connect(temp) as dst:
			dst.executescript("""
				CREATE TABLE metadata(
					key TEXT PRIMARY KEY,
					value TEXT NOT NULL
				);
				CREATE TABLE linear_use_members(
					object_id TEXT PRIMARY KEY,
					edge_id TEXT NOT NULL,
					edge_percentage_from REAL,
					edge_percentage_to REAL,
					length_m REAL,
					feature_name TEXT NOT NULL,
					wkb BLOB NOT NULL
				);
				CREATE INDEX members_by_edge
					ON linear_use_members(edge_id);
				CREATE TABLE edge_axes(
					edge_id TEXT PRIMARY KEY,
					linear_use_count INTEGER NOT NULL,
					linear_use_object_ids TEXT NOT NULL,
					feature_names TEXT NOT NULL,
					geometry_method TEXT NOT NULL,
					endpoint_snap_max_m REAL NOT NULL,
					mean_axis_length_m REAL NOT NULL,
					sample_points INTEGER NOT NULL,
					reversed_lines INTEGER NOT NULL,
					source_length_min_m REAL NOT NULL,
					source_length_max_m REAL NOT NULL,
					length_ratio_min_max REAL NOT NULL,
					max_correspondence_spread_m REAL NOT NULL,
					mean_correspondence_spread_m REAL NOT NULL,
					wkb BLOB NOT NULL
				);
			""")
			for item in members:
				dst.execute(
					"INSERT INTO linear_use_members VALUES (?,?,?,?,?,?,?)",
					(item["object_id"],item["edge_id"],
						item["edge_percentage_from"],
						item["edge_percentage_to"],item["length_m"],
						item["feature_name"],dumps(item["geometry"])))
			for item in axes:
				audit=item["audit"]
				dst.execute(
					"INSERT INTO edge_axes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
					(item["edge_id"],item["source_count"],
						_json_list(item["object_ids"]),
						_json_list(item["feature_names"]),
						audit.method,audit.endpoint_snap_max_m,
						item["geometry"].length,audit.sample_points,
						audit.reversed_lines,audit.min_length_m,
						audit.max_length_m,audit.length_ratio_min_max,
						audit.max_correspondence_spread_m,
						audit.mean_correspondence_spread_m,
						dumps(item["geometry"])))
			meta={
				"schema":SCHEMA,
				"created_utc":datetime.now(timezone.utc).isoformat(),
				"source_path":str(source.resolve()),
				"source_sha256":source_sha,
				"aoi_sha256":aoi_sha,
				"source_crs":source_crs.to_string(),
				"target_crs":TARGET_CRS,
				"base_type":BASE_TYPE,
				"sample_spacing_m":sample_spacing_m,
				"linear_use_rows_base_type_1":total_base_type_1,
				"spatial_prefilter":"gpkg_rtree" if used_rtree else "none",
				"linear_use_rows_spatial_candidates":candidate_rows,
				"linear_use_rows_in_aoi":selected_rows,
				"edge_axes":len(axes),
				"multi_line_edge_ids":sum(
					item["source_count"]>1 for item in axes),
				"snapped_segment_edge_ids":sum(
					item["audit"].method=="endpoint_snap_merge" for item in axes),
				"merged_segment_edge_ids":sum(
					item["audit"].method=="line_merge" for item in axes),
				"mean_axis_edge_ids":sum(
					item["audit"].method=="mean_axis" for item in axes),
				"max_linear_use_per_edge":max(
					item["source_count"] for item in axes),
			}
			dst.executemany("INSERT INTO metadata VALUES (?,?)",
				((key,json.dumps(value,ensure_ascii=False))
					for key,value in meta.items()))
			if dst.execute("PRAGMA quick_check").fetchone()[0]!="ok":
				raise ValueError("LINEAR_USE-Cache ist beschädigt")
		_write_geojson(geojson,axes)
		temp.replace(output_db)
		report={
			**meta,
			"cache":str(output_db),
			"geojson":str(geojson),
			"geojson_sha256":checksum(geojson),
		}
		print(
			f"LINEAR_USE: {selected_rows} base_type=1-Linien in Wien, "
			f"{len(axes)} edge_id-Achsen, "
			f"{report['multi_line_edge_ids']} Gruppen mit mehreren Linien",
			flush=True)
		return report
	except BaseException:
		temp.unlink(missing_ok=True)
		if not output_db.exists():
			geojson.unlink(missing_ok=True)
		raise


def main():
	parser=argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--source",type=Path,required=True)
	parser.add_argument("--aoi",type=Path,required=True)
	parser.add_argument("--out",type=Path,required=True,
		help="Dauerhafter SQLite-Cache der LINEAR_USE-Mittelachsen")
	parser.add_argument("--geojson",type=Path,required=True,
		help="WGS84-Kontroll-GeoJSON der Mittelachsen")
	parser.add_argument("--sample-spacing-m",type=float,default=5.0)
	args=parser.parse_args()
	print(json.dumps(build(
		args.source,args.aoi,args.out,args.geojson,
		sample_spacing_m=args.sample_spacing_m),
		ensure_ascii=False,indent=2))


if __name__=="__main__":
	main()
