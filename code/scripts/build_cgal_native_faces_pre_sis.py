"""Native CGAL segment Voronoi Face -> original edge_id -> dissolve, BEFORE SIS.

The native Voronoi_diagram_2 Face already knows its supporting site.
C++ serializes the Face CCB and original input supporting segment; Python
assembles that ONE Face's ordered halfedges. No global polygonize_full,
point probe, site/polygon spatial join or inferred owner is used.
CGAL point-site faces are deliberately omitted.
"""
import argparse
from collections import defaultdict
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile

from pyproj import Transformer
from shapely import union_all
from shapely.geometry import box, mapping

from scripts.build_cgal_voronoi_geojson import (
	_source_records, _frame, _payload, _connected_components,
	_export_wgs84_polygon)
from scripts.cgal_segment_input import SCALE, _noded_segments
from scripts.cgal_native_faces import read_native_faces
from scripts.wienwide_grid import checksum, load_aoi


def _cache_paths(out):
	return (out.with_name(out.stem+"__native_faces.txt"),
		out.with_name(out.stem+"__native_faces_meta.json"))


def _identity(cache,aoi,binary):
	return {
		"schema":"cgal-native-face-stream-v1",
		"source_sha256":checksum(cache),
		"aoi_sha256":checksum(aoi),
		"binary_sha256":checksum(binary),
		"segment_code_sha256":checksum(
			Path(__file__).with_name("cgal_segment_input.py")),
		"payload_code_sha256":checksum(
			Path(__file__).with_name("build_cgal_voronoi_geojson.py")),
	}


def _write_json_atomic(path,payload):
	path=Path(path)
	with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",
			dir=path.parent,prefix="."+path.name+".",
			suffix=".tmp",delete=False) as stream:
		tmp=Path(stream.name)
		try:
			json.dump(payload,stream,ensure_ascii=False,
				separators=(",",":"),allow_nan=False)
			stream.write("\n")
			stream.flush()
			os.replace(tmp,path)
		finally:
			tmp.unlink(missing_ok=True)


def _read_or_compute_faces(owners,frame,binary,bounds,out,identity,timeout):
	faces_path,meta_path=_cache_paths(out)
	if faces_path.is_symlink() or meta_path.is_symlink():
		raise ValueError("CGAL-Face-Cache darf kein Symlink sein")
	if faces_path.exists() != meta_path.exists():
		raise ValueError("Unvollständiger CGAL-Face-Cache. "
			"Beide Dateien zur Reparatur erst archivieren.")
	if faces_path.exists():
		saved=json.loads(meta_path.read_text(encoding="utf-8"))
		if saved.get("identity")!=identity:
			raise ValueError("CGAL-Face-Cache passt nicht zu Originaldaten "
				"oder C++-Version. Alte Cache-Dateien zuerst archivieren.")
		if not faces_path.stat().st_size:
			raise ValueError("CGAL-Face-Cache ist leer")
		print(f"CGAL: nativen Face-Export wiederverwenden: {faces_path}",flush=True)
		return faces_path,saved["cgal"]
	payload="".join(_payload(owners,frame))
	faces_path.parent.mkdir(parents=True,exist_ok=True)
	with tempfile.NamedTemporaryFile(dir=faces_path.parent,
			prefix="."+faces_path.name+".",suffix=".tmp",
			delete=False) as tmp:
		stage=Path(tmp.name)
	try:
		command=[str(Path(binary).resolve()),"--faces",str(stage)]
		try:
			proc=subprocess.run(command,input=payload,text=True,
				capture_output=True,timeout=timeout,check=False)
		except subprocess.TimeoutExpired as exc:
			raise RuntimeError("CGAL-Face-Export: Timeout") from exc
		if proc.returncode:
			raise RuntimeError("CGAL-Face-Export fehlgeschlagen: "
				+proc.stderr[-3000:])
		cgal=json.loads(proc.stdout)
		if cgal.get("status")!="ok" or cgal.get("segment_faces",0)<=0:
			raise ValueError("CGAL meldete keine nativen Segment-Faces")
		if cgal.get("draw_rays") or cgal.get("draw_lines"):
			raise ValueError("CGAL gab unendliche Halfedges "
				"innerhalb begrenzter Voronoi-Faces aus")
		if not stage.stat().st_size:
			raise ValueError("CGAL-Face-Ausgabe leer")
		os.replace(stage,faces_path)
		_write_json_atomic(meta_path,{"identity":identity,"cgal":cgal})
	finally:
		stage.unlink(missing_ok=True)
	print("CGAL: native Voronoi-Faces gespeichert: "
		f"{cgal['segment_faces']:,} Segment-Faces, "
		f"{cgal['point_faces_omitted']:,} Punkt-Faces ausgelassen",
		flush=True)
	return faces_path,cgal


def _dissolve(groups):
	for edge_id in sorted(groups):
		geom=union_all(groups[edge_id])
		if geom.is_empty or not geom.is_valid:
			raise ValueError(f"{edge_id}: vereinigte CGAL-Fläche ungültig")
		for connected in _connected_components(geom):
			yield edge_id,connected


def build(cache,aoi_path,binary,out,*,timeout=900):
	out=Path(out)
	if out.exists() or out.is_symlink():
		raise FileExistsError(out)
	if not Path(binary).is_file():
		raise FileNotFoundError(binary)
	if not math.isfinite(timeout) or timeout<=0:
		raise ValueError("Timeout muss positiv sein")
	aoi=load_aoi(aoi_path)
	window=box(*aoi.bounds)
	records=_source_records(cache)
	owners,origin=_noded_segments(
		[(edge_id,line) for _object_id,edge_id,line in records],
		progress=lambda message:print(message,flush=True))
	frame=_frame(aoi,origin)
	bounds=list(window.bounds)
	out.parent.mkdir(parents=True,exist_ok=True)
	face_stream,cgal_stats=_read_or_compute_faces(
		owners,frame,binary,bounds,out,
		_identity(cache,aoi_path,binary),timeout)
	groups,stats=read_native_faces(face_stream,owners,origin,aoi,
		progress=lambda message:print(message,flush=True))
	if not groups:
		raise ValueError("Keine nativen CGAL-Segmentflächen im Stadtfenster")
	print(f"CGAL vor SIS: {stats['segment_faces_inside_window']:,} "
		f"native Segment-Faces, {stats['original_edge_ids']:,} edge_ids; "
		f"{stats.get('segment_faces_outside_aoi_bbox',0):,} außerhalb AOI-Hülle übersprungen",
		flush=True)
	to_wgs=Transformer.from_crs(31256,4326,always_xy=True).transform
	to_metric=Transformer.from_crs(4326,31256,always_xy=True).transform
	features=[]
	repairs=[]
	source_area=sum(geom.area for group in groups.values() for geom in group)
	merged_area=0.0
	for edge_id,connected in _dissolve(groups):
		wgs,repair=_export_wgs84_polygon(
			connected,to_wgs,to_metric,edge_id=edge_id)
		merged_area+=connected.area
		if repair:
			repairs.append(repair)
		features.append({"type":"Feature",
			"properties":{"edge_id":edge_id,"area_m2":connected.area,
				"method":"cgal_native_segment_face_pre_sis"},
			"geometry":mapping(wgs)})
	if not features:
		raise ValueError("CGAL-Dissolve vor SIS lieferte keine Flächen")
	# Do not permit silent area loss during grouping. Overlaps between
	# native Face polygons would surface as a nonzero area difference.
	delta=source_area-merged_area
	if abs(delta)>max(0.01,source_area*1e-9):
		raise ValueError(f"CGAL-Face-Flächenbilanz vor SIS verletzt: "
			f"unvereinigte Fläche {delta:.6g} m²")
	collection={"type":"FeatureCollection","features":features,
		"metadata":{"schema":"cgal-native-face-dissolve-pre-sis-v1",
			"crs":"EPSG:4326","source_segments":len(owners),
			"native_cgal":cgal_stats,"native_faces":stats,
			"source_area_m2":source_area,"dissolved_area_m2":merged_area,
			"export_geometry_repairs":repairs,
			"site_ownership_method":"direct_native_voronoi_face_dual_site",
			"point_site_cells_assigned":False,
			"clipped_to_existing_aoi":True,
			"sis_clipped":False,"experimental":True}}
	_write_json_atomic(out,collection)
	print(f"CGAL vor SIS: {len(features):,} zusammenhängende "
		f"Flächen nach edge_id; {out}",flush=True)
	return len(features)


def main():
	parser=argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--cache",type=Path,required=True)
	parser.add_argument("--aoi",type=Path,required=True)
	parser.add_argument("--binary",type=Path,required=True)
	parser.add_argument("--out",type=Path,required=True)
	parser.add_argument("--timeout",type=float,default=900)
	args=parser.parse_args()
	build(args.cache,args.aoi,args.binary,args.out,timeout=args.timeout)


if __name__=="__main__":
	main()
