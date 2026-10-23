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
from shapely import union_all,make_valid
from shapely.validation import explain_validity
from shapely.geometry import box,shape
from shapely.wkb import loads
from shapely.ops import transform
from shapely.strtree import STRtree

from scripts.clip_cgal_with_sis import _validate_index
from scripts.sis_belagsflaechen import VEGETATION_CODES
from scripts.sis_wien_source import vegetation_mask
from scripts.wienwide_grid import read_manifest,checksum
from scripts.wienwide_grm2023 import read_mask,mask_path


def _polygonal_parts(geometry):
	"""Return all polygonal members without creating or reshaping surfaces."""
	if geometry.geom_type in ("Polygon","MultiPolygon"):
		return geometry
	parts=[]
	for member in getattr(geometry,"geoms",()):
		if member.geom_type in ("Polygon","MultiPolygon"):
			parts.extend(getattr(member,"geoms",(member,)))
	return union_all(parts) if parts else None


def _sis_features(path):
	"""Iterate streamed finished SIS GeoJSON without loading all Vienna."""
	with Path(path).open(encoding="utf-8") as stream:
		if stream.readline().strip()!='{"type":"FeatureCollection","features":[':
			raise ValueError("Erwartet zeilenweise geschriebenes fertiges SIS-GeoJSON")
		found_metadata=False
		for line in stream:
			raw=line.strip()
			if not raw:
				continue
			if raw.startswith('],"metadata":'):
				meta=json.loads('{"type":"FeatureCollection","features":[]'+raw[1:]).get("metadata",{})
				if (meta.get("sis_provider")!="SISBELAGOGD"
						and meta.get("schema")!="cgal-sis-grm-ground-v1"):
					raise ValueError("Eingabe enthält keinen fertigen SIS-Verschnitt")
				found_metadata=True
				break
			feature=json.loads(raw[:-1] if raw.endswith(",") else raw)
			if feature.get("type")!="Feature":
				raise ValueError("Ungültiges Feature im SIS-GeoJSON")
			yield feature
		if not found_metadata:
			raise ValueError("SIS-GeoJSON abgeschnitten, Metadaten fehlen")


def _read_finished_metadata(path):
	"""Read the terminal metadata record of a streamed FeatureCollection."""
	with Path(path).open(encoding="utf-8") as stream:
		for line in stream:
			if line.startswith('],"metadata":'):
				return json.loads(
					'{"type":"FeatureCollection","features":[]'+line[1:]
				).get("metadata",{})
	raise ValueError(f"Abgeschnittene GeoJSON-Ausgabe ohne Metadaten: {path}")


def finished_output_is_current(source,out):
	"""Whether a completed statistics cache belongs to this exact SIS input.

	The old output format intentionally has no input digest.  Such a file is
	usable for inspection, but must never be silently accepted as a resumable
	statistics cache.
	"""
	source,out=Path(source),Path(out)
	if not out.is_file():
		return False
	meta=_read_finished_metadata(out)
	return (
		meta.get("schema")=="cgal-sis-grm-ground-v1"
		and meta.get("source_sha256")==checksum(source)
		and isinstance(meta.get("statistics"),dict)
	)

def _metric_geometry_for_statistics(feature, to_metric, edge_id):
	"""Safeguard against tiny invalid rings created by inverse CRS projection.

	Only a negligible topological adjustment is allowed for the statistics
	geometry. The published source feature remains byte-for-byte equivalent
	at the geometry-object level.
	"""
	source=shape(feature["geometry"])
	if source.is_empty or not source.is_valid:
		raise ValueError(f"{edge_id}: SIS-Quellgeometrie ungültig: {explain_validity(source)}")
	metric=transform(to_metric,source)
	if metric.is_empty:
		raise ValueError(f"{edge_id}: metrische Eingabegeometrie leer")
	if metric.is_valid:
		return metric
	reason=explain_validity(metric)
	full_repair=make_valid(metric)
	repaired=_polygonal_parts(full_repair)
	if repaired is None or repaired.is_empty or not repaired.is_valid:
		raise ValueError(f"{edge_id}: metrische Rückprojektion ungültig ({reason}); "
			"keine rein polygonale Korrektur möglich")
	# A GeometryCollection is acceptable only when make_valid added/remained
	# line/point debris with exactly zero area.  Keep solely its polygonal
	# members; this is not a buffer, simplification, or substitute geometry.
	discarded=[member for member in getattr(full_repair,"geoms",())
		if member.geom_type not in ("Polygon","MultiPolygon")]
	if any(member.area!=0 for member in discarded):
		raise ValueError(f"{edge_id}: metrische Rückprojektion ungültig ({reason}); "
			"make_valid enthält flächenhaltige nichtpolygonale Bestandteile")
	# A self-intersecting shape may lose topology. Do not silently count a
	# materially different surface; repair only extremely small CRS artefacts.
	delta=abs(repaired.area-metric.area)
	limit=max(.05,1e-6*max(metric.area,repaired.area))
	if delta>limit:
		raise ValueError(f"{edge_id}: metrische Rückprojektion ungültig ({reason}); "
			f"make_valid verändert Fläche um {delta:.6f} m² (Limit {limit:.6f} m²)")
	try:
		symmetric_difference=metric.symmetric_difference(repaired).area
	except Exception as exc:
		raise ValueError(f"{edge_id}: metrische Rückprojektion ungültig ({reason}); "
			f"symmetrische Differenz nicht prüfbar: {exc}") from exc
	if symmetric_difference>limit:
		raise ValueError(f"{edge_id}: metrische Rückprojektion ungültig ({reason}); "
			f"symmetrische Differenz {symmetric_difference:.6f} m² überschreitet "
			f"{limit:.6f} m²")
	shift=metric.boundary.hausdorff_distance(repaired.boundary)
	if shift==shift and shift>.02:
		raise ValueError(f"{edge_id}: metrische Rückprojektion ungültig ({reason}); "
			f"Randverschiebung {shift:.6f} m überschreitet 0.02 m")
	return repaired


def _intersection_area(a,b):
	if b is None or b.is_empty:
		return 0.
	return a.intersection(b).area


def _get_canopy(tile,*,root,manifest_path,manifest,aoi,manifest_sha,raw_root,cache,validated):
	key=tile["id"]
	if key in cache:
		cache.move_to_end(key)
		return cache[key]
	if key not in validated:
		# Verify source PNG checksums and mask provenance only once
		# per tile; edge_ids are spatially unordered in the GeoJSON.
		canopy,_=read_mask(root,tile,manifest=manifest_path,aoi=aoi,
			manifest_sha256=manifest_sha,raw_root=raw_root)
		validated.add(key)
	else:
		path=mask_path(root,tile)
		uri="file:"+quote(str(path.resolve()),safe="/")+"?mode=ro"
		with sqlite3.connect(uri,uri=True) as db:
			record=db.execute("SELECT geom FROM canopy").fetchone()
		if record is None:
			raise ValueError(f"{key}: gespeicherte GRM-Maske fehlt")
		canopy=loads(record[0])
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
		if finished_output_is_current(source,out):
			return _read_finished_metadata(out)["statistics"]
		raise FileExistsError(
			f"{out}: vorhandene Statistik-Ausgabe ist nicht mit der aktuellen "
			"SIS-Eingabe kompatibel; --replace-existing ist erforderlich"
		)
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
		validated_tiles=set()
		try:
			with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",
					dir=out.parent,prefix=out.name+".",suffix=".tmp",
					delete=False) as writer:
				stage=Path(writer.name)
				writer.write('{"type":"FeatureCollection","features":[\n')
				first=True
				for feature in _sis_features(source):
					props=feature["properties"]
					edge_id=props.get("edge_id")
					if not edge_id or not props.get("sis_clipped"):
						raise ValueError("Eingabe benötigt SIS-verschnittene CGAL-edge_ids")
					geom=_metric_geometry_for_statistics(feature,to_metric,edge_id)
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
							cache=canopy_cache,validated=validated_tiles)
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
					"source_sha256":checksum(source),
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
