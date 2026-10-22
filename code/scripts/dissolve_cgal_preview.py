"""Cut historic TURN_USE node convex hulls from CGAL Faces BEFORE edge_id union.

Inputs are the EXISTING precheck-preview GeoJSON features with native
CGAL site provenance. Do not rerun CGAL, alter ownership, clip to SIS,
repair polygons or silently turn disconnected pieces into MultiPolygon.

Historically used GIP2 node TURN_USE convex hulls are subtracted from each
source Face in EPSG:31256. The original source Face is retained in debug.

One valid contiguous Polygon per edge_id is written to the regular
GeoJSON. If any source polygon is invalid, the union fails, or the
result is not a single valid Polygon, the entire edge_id is put into
a JSON failure report and ALL its original source Faces into a separate
debug GeoJSON. Other edge_ids continue processing.

Since the preview may replace bad CGAL halfedges by straight endpoint
chords, these dissolved polygons remain REVIEW output, not assured
CGAL geometry / SIS-ready production input.

The preview writer serializes each Feature on a single line. This
reader deliberately streams exactly that format into a temporary
SQLite table, so the full Vienna preview need not fit in RAM.
"""
import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile

from pyproj import Transformer
from shapely import union_all
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import transform
from shapely.strtree import STRtree

from scripts.cgal_turn_use_hulls import load_turn_use_hulls
from scripts.wienwide_grid import load_aoi
from shapely.validation import explain_validity


SCHEMA="cgal-original-edge-id-turn-use-hull-dissolve-v2"


def _json_line_features(path):
	"""Read the documented single-feature-per-line CGAL preview format."""
	with Path(path).open(encoding="utf-8") as source:
		header=source.readline().strip()
		if header!='{"type":"FeatureCollection","features":[':
			raise ValueError("CGAL-Dissolve benötigt unser zeilenweises "
				"natives __preview.geojson (nicht ein beliebiges GeoJSON)")
		trailer=None
		for line_number,line in enumerate(source,2):
			line=line.strip()
			if not line:
				continue
			if line.startswith('],"metadata":'):
				if trailer is not None:
					raise ValueError("Mehrere GeoJSON-Endabschnitte")
				# Reconstitute the tiny metadata object without
				# reading the feature array into memory.
				doc=json.loads('{"type":"FeatureCollection","features":[]'+line[1:])
				trailer=doc.get("metadata")
				break
			raw=line[:-1] if line.endswith(",") else line
			try:
				feature=json.loads(raw)
			except json.JSONDecodeError as exc:
				raise ValueError(
					f"CGAL-Vorschau Feature-Zeile {line_number} ungültig") from exc
			if feature.get("type")!="Feature":
				raise ValueError(f"CGAL-Vorschau Zeile {line_number}: kein Feature")
			yield feature
		if not isinstance(trailer,dict):
			raise ValueError("CGAL-Vorschau hat keinen vollständigen Endabschnitt")
		if trailer.get("point_faces_assigned")!="original_inner_only":
			raise ValueError("CGAL-Dissolve erwartet eine Vorschau mit "
				"selektierten ORIGINALEN inneren Punkt-Faces")
		if trailer.get("geometry_validated") is not False:
			raise ValueError("Die Quelle ist keine ungeprüfte native Vorschau")
		if source.read().strip():
			raise ValueError("CGAL-Vorschau enthält Daten nach FeatureCollection-Ende")


def _index_preview(path,db,progress=None):
	db.executescript("""
		CREATE TABLE faces(
			edge_id TEXT NOT NULL,
			face_number INTEGER NOT NULL,
			generator_type TEXT NOT NULL,
			fallback INTEGER NOT NULL,
			feature_json TEXT NOT NULL
		);
		CREATE INDEX idx_faces_edge_id ON faces(edge_id,face_number);
	""")
	pending=[]
	counts=Counter()
	for feature in _json_line_features(path):
		props=feature.get("properties") or {}
		edge_id=props.get("edge_id")
		number=props.get("face_number")
		generator_type=props.get("generator_type")
		if not isinstance(edge_id,str) or not edge_id:
			raise ValueError("CGAL-Vorschau enthält eine Face ohne originale edge_id")
		if type(number) is not int or number<=0:
			raise ValueError(f"{edge_id}: Face ohne gültige face_number")
		if generator_type not in ("segment","inner_point"):
			raise ValueError(f"{edge_id}: unerwarteter generator_type")
		if props.get("preview_only") is not True:
			raise ValueError(f"{edge_id}: Quelle ist keine markierte Vorschau-Face")
		if not isinstance(feature.get("geometry"),dict):
			raise ValueError(f"{edge_id}: Source-GeoJSON-Geometrie fehlt")
		pending.append((edge_id,number,generator_type,
			int(bool(props.get("fallback",False))),
			json.dumps(feature,ensure_ascii=False,separators=(",",":"))))
		counts["source_faces"]+=1
		counts["source_"+generator_type+"_faces"]+=1
		if len(pending)>=1000:
			db.executemany("INSERT INTO faces VALUES(?,?,?,?,?)",pending)
			pending.clear()
		if progress and counts["source_faces"]%20000==0:
			progress(f"CGAL-Dissolve: {counts['source_faces']:,} Vorschau-Faces eingelesen")
	if pending:
		db.executemany("INSERT INTO faces VALUES(?,?,?,?,?)",pending)
	if not counts["source_faces"]:
		raise ValueError("CGAL-Vorschau enthält keine Faces")
	db.commit()
	return counts


def _write_feature(stream,feature,first):
	if not first:
		stream.write(",\n")
	json.dump(feature,stream,ensure_ascii=False,separators=(",",":"),
		allow_nan=False)
	return False


def dissolve(preview,out,debug,report,*,progress=None,junction_hulls=None,
		junction_metadata=None):
	preview,out,debug,report=map(Path,(preview,out,debug,report))
	if not preview.is_file() or preview.is_symlink():
		raise FileNotFoundError(f"CGAL-Vorschau fehlt: {preview}")
	for target in (out,debug,report):
		if target.exists() or target.is_symlink():
			raise FileExistsError(f"Vorhandene Ausgabe wird nicht überschrieben: {target}")
		target.parent.mkdir(parents=True,exist_ok=True)
	if len({str(path.resolve()) for path in (preview,out,debug,report)})!=4:
		raise ValueError("Quelle, Ausgaben und Bericht müssen unterschiedliche Dateien sein")

	to_metric=Transformer.from_crs(4326,31256,always_xy=True).transform
	to_wgs=Transformer.from_crs(31256,4326,always_xy=True).transform
	stats=Counter()
	failures=[]
	accepted_fallbacks=0
	# Use the same all-TURN_USE convex hull geometry as the historic
	# GIP2 SIS-V2 pipeline. A face is cut BEFORE it is united with
	# neighbouring faces that carry the same original edge_id.
	if junction_hulls is None:
		junction_hulls=[]
	hull_geometries=[geom for _,geom in junction_hulls]
	if any(geom.is_empty or not geom.is_valid or
			geom.geom_type not in ("Polygon","MultiPolygon")
			for geom in hull_geometries):
		raise ValueError("TURN_USE-Ausschluss enthält ungültige Hüllengeometrie")
	hull_tree=STRtree(hull_geometries) if hull_geometries else None
	with tempfile.TemporaryDirectory(
			prefix="cgal-dissolve-",dir=out.parent) as staging:
		stage=Path(staging)
		with sqlite3.connect(stage/"faces.sqlite") as db:
			sources=_index_preview(preview,db,progress=progress)
			with (stage/"merged.geojson").open("w",encoding="utf-8") as good, (
					stage/"debug.geojson").open("w",encoding="utf-8") as bad:
				good.write('{"type":"FeatureCollection","features":[\n')
				bad.write('{"type":"FeatureCollection","features":[\n')
				first_good=True
				first_bad=True
				for (edge_id,) in db.execute(
						"SELECT DISTINCT edge_id FROM faces ORDER BY edge_id"):
					rows=db.execute(
						"SELECT face_number,generator_type,fallback,feature_json "
						"FROM faces WHERE edge_id=? ORDER BY face_number",
						(edge_id,)).fetchall()
					stats["edge_ids_checked"]+=1
					parts=[]
					area_sum=0.0
					types=Counter()
					fallback_count=0
					reason=None
					detail=None
					for number,kind,fallback,raw in rows:
						types[kind]+=1
						fallback_count+=fallback
						try:
							feature=json.loads(raw)
							geometry=shape(feature["geometry"])
							if not isinstance(geometry,Polygon):
								reason="source_not_polygon"
								detail=f"Face {number}: {geometry.geom_type}"
								break
							if geometry.is_empty or geometry.area<=0 or not geometry.is_valid:
								reason="source_invalid_polygon"
								detail=f"Face {number}: {explain_validity(geometry)}"
								break
							metric=transform(to_metric,geometry)
							if not metric.is_valid or metric.is_empty or metric.area<=0:
								reason="projection_invalid"
								detail=f"Face {number}: {explain_validity(metric)}"
								break
							# Historical TURN_USE convex junction cut goes HERE,
							# strictly before union_all(parts) by edge_id.
							if hull_tree is not None:
								indices=hull_tree.query(metric,predicate="intersects")
								if len(indices):
									local_mask=union_all([hull_geometries[int(i)]
										for i in indices])
									cut=metric.difference(local_mask)
									if not cut.is_empty and not cut.is_valid:
										raise ValueError("TURN_USE-Differenz ungültig")
									if not cut.is_empty and cut.geom_type not in (
											"Polygon","MultiPolygon"):
										raise ValueError("TURN_USE-Differenz ist "
												+cut.geom_type+" statt Polygon/MultiPolygon")
									removed=max(0.,metric.area-cut.area)
									if removed>1e-8:
										stats["faces_cut_by_turn_use"]+=1
										stats["turn_use_removed_area_sum_m2"]+=removed
									if cut.is_empty:
										stats["faces_entirely_removed_by_turn_use"]+=1
										continue
									metric=cut
							parts.append(metric)
							area_sum+=metric.area
						except Exception as exc:
							reason=("turn_use_cut_error"
								if "TURN_USE" in str(exc) else "source_geometry_error")
							detail=f"Face {number}: {type(exc).__name__}: {exc}"
							break
					joined=None
					if reason is None:
						try:
							joined=union_all(parts)
						except Exception as exc:
							reason="union_error"
							detail=f"{type(exc).__name__}: {exc}"
					if reason is None:
						if joined.is_empty:
							reason="empty_union"
							detail="Union ergab eine leere Geometrie"
						elif joined.geom_type=="MultiPolygon":
							reason="not_contiguous"
							detail=f"{len(joined.geoms)} getrennte Polygone"
						elif not isinstance(joined,Polygon):
							reason="union_not_polygon"
							detail=f"Union ergab {joined.geom_type}"
						elif not joined.is_valid:
							reason="invalid_union"
							detail=explain_validity(joined)
					if reason is None:
						try:
							wgs=transform(to_wgs,joined)
							if not isinstance(wgs,Polygon) or not wgs.is_valid or wgs.is_empty:
								raise ValueError(
									"Projektion liefert kein gültiges Einzelpolygon")
							new_feature={
								"type":"Feature",
								"properties":{
									"edge_id":edge_id,
									"source_face_count":len(rows),
									"segment_face_count":types["segment"],
									"inner_point_face_count":types["inner_point"],
									"fallback_face_count":fallback_count,
									"area_m2":joined.area,
									"preview_based":True,
									"sis_clipped":False,
									"turn_use_hulls_removed":True},
								"geometry":mapping(wgs)}
							first_good=_write_feature(good,new_feature,first_good)
							stats["merged_polygons"]+=1
							stats["accepted_source_faces"]+=len(rows)
							accepted_fallbacks+=fallback_count
							stats["source_overlap_area_m2"]+=max(0,area_sum-joined.area)
						except Exception as exc:
							reason="output_geometry_error"
							detail=f"{type(exc).__name__}: {exc}"
					if reason is not None:
						stats["rejected_edge_ids"]+=1
						stats["rejected_source_faces"]+=len(rows)
						stats["reason_"+reason]+=1
						failures.append({
							"edge_id":edge_id,
							"reason":reason,
							"detail":detail,
							"source_face_count":len(rows),
							"segment_face_count":types["segment"],
							"inner_point_face_count":types["inner_point"],
							"fallback_face_count":fallback_count,
							"turn_use_cut_before_union":True,
							"face_numbers":[number for number,_,_,_ in rows]})
						for _,_,_,raw in rows:
							feature=json.loads(raw)
							props=dict(feature["properties"])
							props["dissolve_error"]=reason
							props["dissolve_error_detail"]=detail
							props["debug_source_face"]=True
							feature["properties"]=props
							first_bad=_write_feature(bad,feature,first_bad)
					if progress and stats["edge_ids_checked"]%1000==0:
						progress(f"CGAL-Dissolve: {stats['edge_ids_checked']:,} edge_ids, "
							f"{stats['merged_polygons']:,} Polygon-Ergebnisse, "
							f"{stats['rejected_edge_ids']:,} Debug-Fälle")
				good.write('\n],"metadata":{"schema":"'+SCHEMA+'",'
					'"preview_based":true,"polygon_only":true,'
					'"point_faces":"original_inner_vertices_only",'
					'"dissolved_by":"edge_id","sis_clipped":false,'
					'"turn_use_hull_cut_before_union":true}}\n')
				bad.write('\n],"metadata":{"schema":"'+SCHEMA+'",'
					'"debug_source_geometries":true}}\n')
		overview={
			"schema":SCHEMA,
			"source_preview":str(preview),
			"turn_use_junctions":{
				"rule":"all_TURN_USE_vertices_convex_hull_by_via_node_id",
				"hull_count":len(hull_geometries),
				"applied_before_edge_id_union":True,
				"source":junction_metadata or {},
			},
			"merged_geojson":str(out),
			"debug_geojson":str(debug),
			"preview_based":True,
			"geometrically_assured":False,
			"sis_clipped":False,
			"source_face_counts":dict(sources),
			"statistics":dict(stats),
			"accepted_fallback_source_faces":accepted_fallbacks,
			"failures":failures,
		}
		(stage/"report.json").write_text(json.dumps(
			overview,ensure_ascii=False,indent=2,allow_nan=False)+"\n",
			encoding="utf-8")
		for temporary,output in (("merged.geojson",out),
				("debug.geojson",debug),("report.json",report)):
			os.replace(stage/temporary,output)
	print(f"CGAL-Dissolve: {stats['merged_polygons']:,} einzelne Polygone, "
		f"{stats['rejected_edge_ids']:,} edge_ids mit Fehlern, "
		f"{accepted_fallbacks:,} Fallback-Quell-Faces in Ergebnissen",flush=True)
	print(f"Ausgabe: {out}\nDebug: {debug}\nBericht: {report}",flush=True)
	return overview


def main():
	parser=argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--preview",type=Path,required=True)
	parser.add_argument("--out",type=Path,required=True)
	parser.add_argument("--debug",type=Path,required=True)
	parser.add_argument("--report",type=Path,required=True)
	parser.add_argument("--turn-use-source",type=Path,required=True,
		help="Originales GIP2 GeoPackage mit NODE/TURN_USE und RTree")
	parser.add_argument("--aoi",type=Path,required=True,
		help="Bestehende Wiener AOI für die historischen Kreuzungshüllen")
	args=parser.parse_args()
	aoi=load_aoi(args.aoi)
	hulls,details=load_turn_use_hulls(args.turn_use_source,aoi,
		progress=lambda message:print(message,flush=True))
	if not hulls:
		raise ValueError("Keine polygonalen TURN_USE-Hüllen erzeugt; "
			"Abbruch statt Voronoi-Dissolve ohne Kreuzungsausschluss")
	print(f"TURN_USE: {len(hulls):,} konvexe NODE-Hüllen "
		"für den Vor-Dissolve-Ausschluss",flush=True)
	dissolve(args.preview,args.out,args.debug,args.report,
		junction_hulls=hulls,junction_metadata=details,
		progress=lambda message:print(message,flush=True))


if __name__=="__main__":
	main()
