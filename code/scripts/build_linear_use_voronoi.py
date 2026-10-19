"""Tiled debug Voronoi of completed LINEAR_USE axes (no FMZK or length clipping).

Each axis is sampled along its geometry. Voronoi is constructed for sampled
points within a tile's buffered neighborhood, then clipped to the tile/AOI.
This approximation is intended for inspection, not quantitative measurements.
"""
import argparse
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile

from pyproj import Transformer
from shapely import geos_version, segmentize, union_all, voronoi_polygons
from shapely.geometry import LineString, MultiPoint, box, mapping
from shapely.ops import transform
from shapely.strtree import STRtree
from shapely.wkb import loads

from scripts.wienwide_grid import load_aoi, plan


def _load_axes(path):
	with sqlite3.connect(path) as db:
		rows=db.execute("SELECT edge_id,wkb FROM edge_axes ORDER BY edge_id").fetchall()
	if not rows:
		raise ValueError("Keine LINEAR_USE-Ergebnisachsen im Cache")
	ids=[]
	geoms=[]
	for edge_id,blob in rows:
		geom=loads(blob)
		if not isinstance(geom,LineString) or geom.is_empty or not geom.is_valid:
			raise ValueError(f"Ungültige Ergebnisachse: {edge_id}")
		ids.append(edge_id)
		geoms.append(geom)
	return ids,geoms


def _polygon_parts(geometry):
	if geometry.is_empty:
		return
	if geometry.geom_type=="Polygon":
		yield geometry
	elif hasattr(geometry,"geoms"):
		for part in geometry.geoms:
			yield from _polygon_parts(part)


def _tile_polygons(ids,geoms,tree,core,*,spacing_m,halo_m):
	search=core.envelope.buffer(halo_m,cap_style="square",join_style="mitre")
	# Same-coordinate points from distinct axes have a deterministic owner.
	seeds={}
	for idx in tree.query(search):
		idx=int(idx)
		section=geoms[idx].intersection(search)
		for part in (section.geoms if hasattr(section,"geoms") else (section,)):
			if not isinstance(part,LineString) or part.is_empty or part.length==0:
				continue
			for x,y,*_ in segmentize(part,spacing_m).coords:
				key=(float(x),float(y))
				owner=ids[idx]
				if key not in seeds or owner<seeds[key]:
					seeds[key]=owner
	if len(seeds)<3:
		raise ValueError("Zu wenige Voronoi-Stützpunkte in Kachel")
	points=list(seeds)
	owners=[seeds[p] for p in points]
	if geos_version<(3,12,0):
		raise RuntimeError("GEOS >= 3.12 für geordnetes Voronoi erforderlich")
	cells=voronoi_polygons(MultiPoint(points),extend_to=search.envelope,ordered=True)
	if len(cells.geoms)!=len(points):
		raise ValueError("Voronoi-Zellzahl stimmt nicht mit Stützpunkten überein")
	pieces={}
	for owner,cell in zip(owners,cells.geoms):
		if not cell.intersects(core):
			continue
		clipped=cell.intersection(core)
		if not clipped.is_empty and clipped.area>0:
			pieces.setdefault(owner,[]).append(clipped)
	for owner,parts in sorted(pieces.items()):
		merged=union_all(parts)
		if not merged.is_empty:
			yield owner,merged


def build(cache,aoi_path,out,*,tile_m=500,halo_m=250,spacing_m=20,max_tiles=None):
	cache,aoi_path,out=map(Path,(cache,aoi_path,out))
	if out.exists() or out.is_symlink():
		raise FileExistsError(out)
	if not math.isfinite(spacing_m) or spacing_m<=0:
		raise ValueError("Abtastabstand muss positiv und endlich sein")
	if halo_m<2*spacing_m:
		raise ValueError("Halo muss mindestens den doppelten Abtastabstand haben")
	aoi=load_aoi(aoi_path)
	ids,geoms=_load_axes(cache)
	tree=STRtree(geoms)
	tiles=plan(aoi,size=tile_m,halo=halo_m)
	if max_tiles is not None:
		if max_tiles<1:
			raise ValueError("max_tiles muss >= 1 sein")
		tiles=tiles[:max_tiles]
	out.parent.mkdir(parents=True,exist_ok=True)
	to_wgs=Transformer.from_crs(31256,4326,always_xy=True).transform
	tmp=None
	features=0
	try:
		with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=out.parent,
				prefix=out.name+".",suffix=".tmp",delete=False) as target:
			tmp=Path(target.name)
			target.write('{"type":"FeatureCollection","features":[')
			for number,tile in enumerate(tiles,1):
				core=box(*tile["bounds_31256"]).intersection(aoi)
				for edge_id,geometry in _tile_polygons(ids,geoms,tree,core,
						spacing_m=spacing_m,halo_m=halo_m):
					for polygon in _polygon_parts(geometry):
						if polygon.area<=0:
							continue
						feature={"type":"Feature","properties":{
							"edge_id":edge_id,"tile_id":tile["id"],
							"area_m2":polygon.area,"debug":True},
							"geometry":mapping(transform(to_wgs,polygon))}
						if features:
							target.write(",\n")
						target.write(json.dumps(feature,ensure_ascii=False,
							separators=(",",":"),allow_nan=False))
						features+=1
				print(f"Voronoi: {number}/{len(tiles)} Kacheln, "
					f"{features} Polygone",flush=True)
			target.write("]}\n")
		os.replace(tmp,out)
		tmp=None
	finally:
		if tmp is not None:
			tmp.unlink(missing_ok=True)
	print(json.dumps({"geojson":str(out),"features":features,
		"tiles":len(tiles),"spacing_m":spacing_m,"halo_m":halo_m,
		"debug_approximation":True},ensure_ascii=False,indent=2))
	return features


def main():
	parser=argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--cache",type=Path,required=True)
	parser.add_argument("--aoi",type=Path,required=True)
	parser.add_argument("--out",type=Path,required=True)
	parser.add_argument("--tile-m",type=int,default=500)
	parser.add_argument("--halo-m",type=int,default=250)
	parser.add_argument("--spacing-m",type=float,default=20)
	parser.add_argument("--max-tiles",type=int,default=None)
	args=parser.parse_args()
	build(args.cache,args.aoi,args.out,tile_m=args.tile_m,
		halo_m=args.halo_m,spacing_m=args.spacing_m,max_tiles=args.max_tiles)


if __name__=="__main__":
	main()
