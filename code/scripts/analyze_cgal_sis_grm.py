"""Ground (SIS BELAG) and canopy (GRM2023) areas for finished CGAL/SIS polygons.

Uses only cached, read-only Vienna data. The input feature geometries and
original edge_id are preserved. Ground vegetation: SIS BELAG BL/ST/WI.
Canopy and ground are independent layers; their overlap is reported, not
double-counted in the combined vegetation coverage.
"""
import argparse
from collections import Counter,OrderedDict
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from urllib.parse import quote

from pyproj import Transformer
from shapely import union_all
from shapely.geometry import box,shape
from shapely.ops import transform
from shapely.strtree import STRtree

from scripts.clip_cgal_with_sis import _features,_validate_index
from scripts.sis_belagsflaechen import VEGETATION_CODES
from scripts.sis_wien_source import vegetation_mask
from scripts.wienwide_grid import read_manifest,checksum
from scripts.wienwide_grm2023 import read_mask,mask_path


def _intersection_area(a,b):
	if b is None or b.is_empty:
		return 0.
	return a.intersection(b).area


def _get_canopy(tile,*,root,manifest_path,manifest,aoi,manifest_sha,raw_root,cache):
	key=tile["id"]
	if key in cache:
		cache.move_to_end(key)
		return cache[key]
	canopy,_=read_mask(root,tile,manifest=manifest_path,aoi=aoi,
		manifest_sha256=manifest_sha,raw_root=raw_root)
	cache[key]=canopy
	if len(cache)>8:
		cache.popitem(last=False)
	return canopy


def analyze(source,sis_db,manifest_path,grm_root,out,*,raw_root=None,
		replace_existing=False,progress=None):
	source,sis_db,manifest_path,grm_root,out=map(Path,
		(source,sis_db,manifest_path,grm_root,out))
	raw_root=Path(raw_root) if raw_root else grm_root
	for p in (source,sis_db,manifest_path):
		if not p.is_file():
			raise FileNotFoundError(p)
	if out.exists() and not replace_existing:
		raise FileExistsError(out)
	if out.is_symlink() or out.resolve()==source.resolve():
		raise ValueError("Ausgabe darf Eingabe nicht überschreiben")
	manifest,aoi=read_manifest(manifest_path)
	tiles=manifest["tiles"]
	tile_bounds=[box(*tile["bounds_31256"]) for tile in tiles]
	tree=STRtree(tile_bounds)
	manifest_sha=checksum(manifest_path)
	# Do not begin writing without a complete local GRM mask set.
	missing=[str(mask_path(grm_root,tile)) for tile in tiles
		if not mask_path(grm_root,tile).is_file()]
	if missing:
		raise FileNotFoundError(f"{len(missing)} GRM-Kachelmasken fehlen, erste: {missing[0]}")
	to_metric=Transformer.from_crs(4326,31256,always_xy=True).transform
	summary=Counter()
	uri="file:"+quote(str(sis_db.resolve()),safe="/")+"?mode=ro"
	out.parent.mkdir(parents=True,exist_ok=True)
	stage=None
	with sqlite3.connect(uri,uri=True) as db:
		sis_meta=_validate_index(db)
		canopy_cache=OrderedDict()
		try:
			with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",
					dir=out.parent,prefix=out.name+".",suffix=".tmp",
					delete=False) as writer:
				stage=Path(writer.name)
				writer.write('{"type":"FeatureCollection","features":[\n')
				first=True
				for feature in _features(source):
					props=feature["properties"]
					edge_id=props.get("edge_id")
					if not edge_id or not props.get("sis_clipped"):
						raise ValueError("Eingabe benötigt SIS-verschnittene CGAL-edge_ids")
					geom=transform(to_metric,shape(feature["geometry"]))
					if geom.is_empty or not geom.is_valid:
						raise ValueError(f"{edge_id}: ungültige Eingabegeometrie")
					area=geom.area
					ground=vegetation_mask(db,geom,VEGETATION_CODES)
					ground_area=_intersection_area(geom,ground)
					crown_pieces=[]
					tile_hits=tree.query(geom,predicate="intersects")
					for index in tile_hits:
						tile=tiles[int(index)]
						crown=_get_canopy(tile,root=grm_root,
							manifest_path=manifest_path,manifest=manifest,aoi=aoi,
							manifest_sha=manifest_sha,raw_root=raw_root,
							cache=canopy_cache)
						if not crown.is_empty and crown.intersects(geom):
							piece=crown.intersection(geom)
							if piece.area>0:
								crown_pieces.append(piece)
					crown_area=0.
					overlap=0.
					if crown_pieces:
						crown_union=union_all(crown_pieces)
						crown_area=crown_union.area
						overlap=_intersection_area(crown_union,ground)
					covered=ground_area+crown_area-overlap
					# Floating point noise does not denote a new surface.
					covered=max(0.,min(area,covered))
					props=dict(props)
					props.update({
						"boden_begruent_m2":ground_area,
						"boden_sonstig_m2":max(0.,area-ground_area),
						"grm2023_baumkronen_m2":crown_area,
						"baumkronen_ueber_begruentem_boden_m2":overlap,
						"vegetation_boden_oder_krone_m2":covered,
						"vegetation_boden_oder_krone_pct":(
							100*covered/area if area>0 else 0.),
					})
					out_feature={**feature,"properties":props}
					if not first:
						writer.write(",\n")
					json.dump(out_feature,writer,ensure_ascii=False,
						separators=(",",":"),allow_nan=False)
					first=False
					summary["features"]+=1
					if ground_area:
						summary["features_with_green_ground"]+=1
					if crown_area:
						summary["features_with_canopy"]+=1
					if progress and summary["features"]%1000==0:
						progress(f"SIS/GRM-Auswertung: {summary['features']:,} edge_ids")
				writer.write('\n],"metadata":')
				json.dump({"schema":"cgal-sis-grm-ground-v1",
					"source":str(source),
					"sis_sha256":sis_meta["sha256"],
					"grm_manifest_sha256":manifest_sha,
					"grm_method":"grm2023-rgb-canopy-v1",
					"ground_vegetation_belag_codes":sorted(VEGETATION_CODES),
					"ground_rule":"green SIS union minus other SIS belags",
					"ground_and_canopy_overlap_counted_once":True,
					"statistics":dict(summary)},writer,
					ensure_ascii=False,separators=(",",":"))
				writer.write("}\n")
				writer.flush()
			os.replace(stage,out)
		finally:
			if stage is not None:
				stage.unlink(missing_ok=True)
	return dict(summary)


def main():
	p=argparse.ArgumentParser(description=__doc__)
	p.add_argument("--source",type=Path,required=True)
	p.add_argument("--sis-db",type=Path,required=True)
	p.add_argument("--manifest",type=Path,required=True)
	p.add_argument("--grm-root",type=Path,required=True)
	p.add_argument("--raw-root",type=Path)
	p.add_argument("--out",type=Path,required=True)
	p.add_argument("--replace-existing",action="store_true")
	a=p.parse_args()
	stats=analyze(a.source,a.sis_db,a.manifest,a.grm_root,a.out,
		raw_root=a.raw_root,replace_existing=a.replace_existing,
		progress=lambda value:print(value,flush=True))
	print(f"SIS/GRM-Auswertung abgeschlossen: {stats['features']:,} edge_ids; {a.out}")


if __name__=="__main__":
	main()
