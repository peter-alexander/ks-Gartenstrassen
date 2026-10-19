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
from functools import lru_cache

from pyproj import Transformer
from shapely import geos_version, make_valid, segmentize, union_all, voronoi_polygons, intersection
from shapely.geometry import LineString, MultiPoint, box, mapping
from shapely.ops import transform
from shapely.strtree import STRtree
from shapely.wkb import loads
from shapely.errors import GEOSException

from scripts.wienwide_grid import load_aoi, plan, read_manifest, checksum
from scripts.wienwide_street import load_street_tile


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


def _safe_clip(cell,core):
	"""Repair invalid Voronoi polygons without hiding unrecoverable failures."""
	try:
		if cell.is_valid:
			return cell.intersection(core)
	except GEOSException:
		pass
	fixed=make_valid(cell)
	if fixed.is_empty or not fixed.is_valid:
		raise ValueError("Voronoi-Polygon lässt sich nicht reparieren")
	try:
		result=fixed.intersection(core)
	except GEOSException:
		# Fixed-precision overlay resolves floating point robustness issues.
		result=intersection(fixed,core,grid_size=1e-7)
	if not result.is_valid:
		result=make_valid(result)
	if not result.is_valid:
		raise ValueError("Voronoi-Verschnitt bleibt ungültig")
	return result


def _robust_voronoi(seeds,extent):
	"""Retry a numerically degenerate GEOS tessellation on a fine grid.

	Grid coordinates and their owners are deduplicated together so that
	ordered=True can never assign a cell to the wrong edge_id.
	"""
	last_error=None
	for grid in (None,0.001,0.01,0.1):
		if grid is None:
			points=list(seeds)
			owners=[seeds[p] for p in points]
		else:
			rounded={}
			for (x,y),owner in seeds.items():
				key=(round(x/grid)*grid,round(y/grid)*grid)
				if key not in rounded or owner<rounded[key]:
					rounded[key]=owner
			points=list(rounded)
			owners=[rounded[p] for p in points]
		if len(points)<3:
			continue
		try:
			cells=voronoi_polygons(MultiPoint(points),
				extend_to=extent,ordered=True)
			if len(cells.geoms)!=len(points):
				raise ValueError("Voronoi-Zellzahl weicht von Stützpunkten ab")
			return owners,cells
		except GEOSException as exc:
			last_error=exc
	raise ValueError(
		"Voronoi scheitert auch mit 1 mm, 1 cm und 10 cm "
		f"Koordinatenraster: {last_error}") from last_error


def _tile_polygons(ids,geoms,tree,core,*,spacing_m,halo_m):
	"""Assign every tile area, including tiles far from the nearest axis."""
	if geos_version<(3,12,0):
		raise RuntimeError("GEOS >= 3.12 für geordnetes Voronoi erforderlich")
	# Bound the search to avoid city-wide Voronoi work in empty tiles.
	# In sparse areas use the nearest axes with a search envelope based
	# on actual nearest distance, rather than repeatedly doubling radius.
	center=core.envelope.centroid
	nearest_idx=int(tree.nearest(center))
	nearest_distance=geoms[nearest_idx].distance(center)
	core_radius=math.hypot(core.bounds[2]-core.bounds[0],
		core.bounds[3]-core.bounds[1])/2
	radius=max(float(halo_m),nearest_distance+core_radius+spacing_m)
	search=core.envelope.buffer(radius,cap_style="square",join_style="mitre")
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
		# In exceptionally sparse areas an entire tile is attributed to
		# its nearest axis for visualization. No huge global tessellation.
		yield ids[nearest_idx],core
		return
	owners,cells=_robust_voronoi(seeds,search.envelope)
	pieces={}
	for owner,cell in zip(owners,cells.geoms):
		if not cell.intersects(core):
			continue
		clipped=_safe_clip(cell,core)
		if not clipped.is_empty and clipped.area>0:
			pieces.setdefault(owner,[]).append(clipped)
	if not pieces:
		raise ValueError("Voronoi-Zellen decken Kachel nicht ab")
	for owner,parts in sorted(pieces.items()):
		try:
			merged=union_all(parts)
		except GEOSException:
			merged=union_all([make_valid(p) for p in parts],grid_size=1e-7)
		if not merged.is_valid:
			merged=make_valid(merged)
		if not merged.is_empty:
			yield owner,merged


def _sis_mask_reader(manifest_path,sis_root,aoi_path):
	"""Read verified SIS tile geometries lazily, regardless of tile size."""
	manifest_path,sis_root=Path(manifest_path),Path(sis_root)
	manifest,aoi=read_manifest(manifest_path)
	if checksum(aoi_path)!=manifest["aoi_sha256"]:
		raise ValueError("SIS-Raster und LINEAR_USE-AOI stimmen nicht überein")
	tiles=manifest["tiles"]
	cores=[box(*tile["bounds_31256"]).intersection(aoi) for tile in tiles]
	tree=STRtree(cores)

	@lru_cache(maxsize=16)
	def load_tile(index):
		tile=tiles[index]
		path=sis_root/tile["id"]/"street.sqlite"
		return load_street_tile(path,cores[index])

	def mask(core):
		parts=[]
		for index in tree.query(core):
			index=int(index)
			overlap=cores[index].intersection(core)
			if overlap.is_empty or overlap.area<=0:
				continue
			sis=load_tile(index)
			if sis.is_empty or not sis.intersects(overlap):
				continue
			piece=_safe_clip(sis,overlap)
			if not piece.is_empty and piece.area>0:
				parts.append(piece)
		return union_all(parts) if parts else None

	return mask


def build(cache,aoi_path,out,*,sis_manifest,sis_root,
		tile_m=500,halo_m=250,spacing_m=20,max_tiles=None):
	cache,aoi_path,out=map(Path,(cache,aoi_path,out))
	if out.exists() or out.is_symlink():
		raise FileExistsError(out)
	if not math.isfinite(spacing_m) or spacing_m<=0:
		raise ValueError("Abtastabstand muss positiv und endlich sein")
	if halo_m<2*spacing_m:
		raise ValueError("Halo muss mindestens den doppelten Abtastabstand haben")
	aoi=load_aoi(aoi_path)
	sis_mask=_sis_mask_reader(sis_manifest,sis_root,aoi_path)
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
				mask=sis_mask(core)
				if mask is None or mask.is_empty:
					print(f"Voronoi: {number}/{len(tiles)} Kacheln, "
						f"{features} Polygone (SIS leer)",flush=True)
					continue
				try:
					polygons=list(_tile_polygons(ids,geoms,tree,core,
						spacing_m=spacing_m,halo_m=halo_m))
				except (GEOSException,ValueError) as exc:
					raise ValueError(f"Voronoi-Kachel {tile['id']}: {exc}") from exc
				for edge_id,geometry in polygons:
					try:
						geometry=_safe_clip(geometry,mask)
					except (GEOSException,ValueError) as exc:
						raise ValueError(
							f"Voronoi/SIS-Schnitt {tile['id']}, {edge_id}: {exc}") from exc
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
		"sis_manifest":str(sis_manifest),"sis_root":str(sis_root),
		"debug_approximation":True},ensure_ascii=False,indent=2))
	return features


def main():
	parser=argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--cache",type=Path,required=True)
	parser.add_argument("--aoi",type=Path,required=True)
	parser.add_argument("--sis-manifest",type=Path,required=True)
	parser.add_argument("--sis-root",type=Path,required=True)
	parser.add_argument("--out",type=Path,required=True)
	parser.add_argument("--tile-m",type=int,default=500)
	parser.add_argument("--halo-m",type=int,default=250)
	parser.add_argument("--spacing-m",type=float,default=20)
	parser.add_argument("--max-tiles",type=int,default=None)
	args=parser.parse_args()
	build(args.cache,args.aoi,args.out,sis_manifest=args.sis_manifest,
		sis_root=args.sis_root,tile_m=args.tile_m,
		halo_m=args.halo_m,spacing_m=args.spacing_m,max_tiles=args.max_tiles)


if __name__=="__main__":
	main()
