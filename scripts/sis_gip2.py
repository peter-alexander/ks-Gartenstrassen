"""Lokaler GIP-2.0-Adapter für SIS-Pilot: EDGE-Sites und NODE/TURN_USE-Hüllen.

Keine Wiener WFS-Daten. Original-GPKG unverändert. EPSG:4326 -> EPSG:31256.
"""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import sqlite3
from urllib.parse import quote

from pyproj import Transformer
from shapely.geometry import MultiPoint, box
from shapely.ops import transform
from shapely.wkb import loads, dumps

from scripts.wienwide_grid import read_manifest, checksum

TO_METRIC = Transformer.from_crs("EPSG:4326", "EPSG:31256", always_xy=True).transform
TO_WGS = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform


def gpkg_geom(blob):
	if blob is None:
		return None
	data = bytes(blob)
	if len(data) < 9 or data[:2] != b"GP":
		raise ValueError("Ungültiger GeoPackage-Geometrieheader")
	flags = data[3]
	envelope = (flags >> 1) & 7
	if envelope > 4:
		raise ValueError("Unbekannter GeoPackage-Envelope")
	offset = 8 + (0, 32, 48, 48, 64)[envelope]
	return loads(data[offset:])


def read_only(path):
	return sqlite3.connect("file:" + quote(str(Path(path).resolve()), safe="/") + "?mode=ro", uri=True)


def build(source, manifest_path, output):
	source, output = Path(source), Path(output)
	if not source.is_file():
		raise FileNotFoundError(source)
	if output.exists():
		raise FileExistsError(output)
	manifest, aoi = read_manifest(manifest_path)
	search = aoi.envelope.buffer(manifest["halo_m"] + 35)
	# Spatial table RTree first; never scan all Austrian WKB geometries.
	wgs_bounds = transform(TO_WGS, search.segmentize(10)).bounds
	sis_bbox = transform(TO_WGS, aoi.envelope.segmentize(10)).bounds
	temp = output.with_suffix(".tmp")
	if temp.exists():
		raise FileExistsError(temp)
	output.parent.mkdir(parents=True, exist_ok=True)
	try:
		with read_only(source) as src, sqlite3.connect(temp) as dst:
			src.row_factory = sqlite3.Row
			needed = ("EDGE", "NODE", "TURN_USE")
			for layer in needed:
				if not src.execute("SELECT 1 FROM gpkg_contents WHERE table_name=?", (layer,)).fetchone():
					raise ValueError(f"Fehlender GIP-Layer: {layer}")
				if not src.execute("SELECT 1 FROM sqlite_master WHERE name=?", ("rtree_" + layer + "_geom",)).fetchone():
					raise ValueError(f"{layer}: räumlicher RTree fehlt")
			dst.executescript("""
				CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
				CREATE TABLE axes(pk INTEGER PRIMARY KEY,gip TEXT UNIQUE NOT NULL,
					name TEXT NOT NULL,fow INTEGER,node_from TEXT NOT NULL,
					node_to TEXT NOT NULL,wkb BLOB NOT NULL);
				CREATE TABLE nodes(pk INTEGER PRIMARY KEY,gip TEXT UNIQUE NOT NULL,
					name TEXT NOT NULL,x REAL NOT NULL,y REAL NOT NULL,wkb BLOB NOT NULL);
				CREATE VIRTUAL TABLE node_spatial USING rtree(pk,minx,maxx,miny,maxy);
				CREATE TABLE node_degrees(gip TEXT PRIMARY KEY,degree INTEGER NOT NULL);
				CREATE TABLE sites(pk INTEGER PRIMARY KEY,axis_pk INTEGER NOT NULL,x REAL NOT NULL,y REAL NOT NULL);
				CREATE VIRTUAL TABLE site_spatial USING rtree(pk,minx,maxx,miny,maxy);
				CREATE INDEX sites_by_axis ON sites(axis_pk);
				CREATE TABLE junctions(node_id TEXT PRIMARY KEY,turn_count INTEGER NOT NULL,
					area_m2 REAL NOT NULL,geom BLOB NOT NULL);
				CREATE VIRTUAL TABLE junction_spatial USING rtree(pk,minx,maxx,miny,maxy);
				CREATE TABLE junction_audit(node_id TEXT PRIMARY KEY,turn_count INTEGER NOT NULL,
					result TEXT NOT NULL,area_m2 REAL NOT NULL);
			""")
			def spatial(layer, bounds):
				x0,y0,x1,y1 = bounds
				return src.execute(f"""SELECT t.* FROM "{layer}" t
					JOIN "rtree_{layer}_geom" r ON r.id=t.fid
					WHERE r.maxx>=? AND r.minx<=? AND r.maxy>=? AND r.miny<=?""",
					(x0,x1,y0,y1))
			axes = 0
			sites = 0
			seen = {}
			duplicate_sites = 0
			for row in spatial("EDGE", wgs_bounds):
				g = gpkg_geom(row["geom"])
				if g is None or g.is_empty:
					continue
				if g.geom_type not in ("LineString", "MultiLineString"):
					raise ValueError(f"EDGE {row['object_id']}: unerwarteter Typ {g.geom_type}")
				g = transform(TO_METRIC, g)
				if not g.intersects(search):
					continue
				edge_id = str(row["object_id"])
				if not edge_id or row["node_from_id"] is None or row["node_to_id"] is None:
					raise ValueError("EDGE ohne UUID/Referenzknoten")
				cur = dst.execute("INSERT INTO axes(gip,name,fow,node_from,node_to,wkb) VALUES (?,?,?,?,?,?)",
					(edge_id, row["mainname_text"] or row["feature_name"] or "",
					row["form_of_way"], str(row["node_from_id"]), str(row["node_to_id"]), dumps(g)))
				axes += 1
				n = max(1,math.ceil(g.length / 5))
				for i in range(n):
					pt = g.interpolate((i+.5)/n, normalized=True)
					if not search.covers(pt):
						continue
					key = (round(pt.x, 7), round(pt.y, 7))
					if key in seen:
						duplicate_sites += 1
						continue
					seen[key] = edge_id
					dst.execute("INSERT INTO sites(axis_pk,x,y) VALUES (?,?,?)",
						(cur.lastrowid, pt.x,pt.y))
					dst.execute("INSERT INTO site_spatial VALUES (?,?,?,?,?)",
						(sites+1,pt.x,pt.x,pt.y,pt.y))
					sites += 1
			if sites < 2:
				raise ValueError("Zu wenige EDGE-Voronoi-Stützpunkte")
			node_ids = {}
			for row in spatial("NODE", sis_bbox):
				g = gpkg_geom(row["geom"])
				if g is None or g.geom_type != "Point" or g.is_empty:
					continue
				if not box(*sis_bbox).covers(g):
					continue
				node_id = str(row["object_id"])
				metric = transform(TO_METRIC,g)
				cur = dst.execute("INSERT INTO nodes(gip,name,x,y,wkb) VALUES (?,?,?,?,?)",
					(node_id,row["feature_name"] or "",metric.x,metric.y,dumps(metric)))
				dst.execute("INSERT INTO node_spatial VALUES (?,?,?,?,?)",
					(cur.lastrowid,metric.x,metric.x,metric.y,metric.y))
				dst.execute("INSERT INTO node_degrees VALUES (?,?)",
					(node_id,row["edge_degree"] or 0))
				node_ids[node_id] = {"points": [], "turn_count": 0}
			if not node_ids:
				raise ValueError("Keine NODE-Punkte innerhalb der SIS-BBOX")
			# via_node_id is the authoritative join; read only lines in the local area.
			for row in spatial("TURN_USE", wgs_bounds):
				node_id = row["via_node_id"]
				if node_id not in node_ids:
					continue
				g = gpkg_geom(row["geom"])
				if g is None or g.is_empty:
					continue
				if g.geom_type not in ("LineString","MultiLineString"):
					raise ValueError(f"TURN_USE {row['object_id']}: keine Linie")
				metric = transform(TO_METRIC,g)
				group = node_ids[node_id]
				group["turn_count"] += 1
				for line in (metric.geoms if metric.geom_type=="MultiLineString" else (metric,)):
					group["points"].extend(line.coords)
			polygon_count = 0
			for node_id, group in node_ids.items():
				num = group["turn_count"]
				coords = group["points"]
				hull = MultiPoint(coords).convex_hull if coords else None
				if hull is None or hull.geom_type != "Polygon" or hull.area <= 0:
					dst.execute("INSERT INTO junction_audit VALUES (?,?,?,?)",
						(node_id,num,"keine_polygonale_huelle",0.))
					continue
				cur = dst.execute("INSERT INTO junctions(node_id,turn_count,area_m2,geom) VALUES (?,?,?,?)",
					(node_id,num,hull.area,dumps(hull)))
				dst.execute("INSERT INTO junction_spatial VALUES (?,?,?,?,?)",
					(cur.lastrowid,* (hull.bounds[0],hull.bounds[2],hull.bounds[1],hull.bounds[3])))
				dst.execute("INSERT INTO junction_audit VALUES (?,?,?,?)",
					(node_id,num,"polygon",hull.area))
				polygon_count += 1
			meta = {"manifest_sha256":checksum(manifest_path),"source_sha256":checksum(source),
				"source":"gip_network_ogd.gpkg",
				"index_method":"gip2-local-edge-turn-use-v1","sampling_m":5,
				"max_axis_distance_m":25,
				"achsen":axes,"voronoi_sites":sites,
				"identische_sites_ausgelassen":duplicate_sites,"knoten":len(node_ids),
				"kreuzungshuelle":polygon_count,
				"crs":"EPSG:31256"}
			for k,v in meta.items():
				dst.execute("INSERT INTO meta VALUES (?,?)",(k,json.dumps(v)))
		temp.replace(output)
	except BaseException:
		temp.unlink(missing_ok=True)
		raise
	return meta


def main():
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("--source",type=Path,required=True)
	p.add_argument("--manifest",type=Path,required=True)
	p.add_argument("--out",type=Path,required=True)
	a = p.parse_args()
	print(json.dumps(build(a.source,a.manifest,a.out),indent=2,ensure_ascii=False))


if __name__=="__main__":
	main()
