"""Cut historic TURN_USE node convex hulls from CGAL Faces BEFORE edge_id union.

Inputs are the EXISTING precheck-preview GeoJSON features with native
CGAL site provenance. Do not rerun CGAL, alter ownership, clip to SIS,
repair polygons or silently turn disconnected pieces into MultiPolygon.

Historically used GIP2 node TURN_USE convex hulls are subtracted from each
source Face in EPSG:31256. The post-TURN_USE-cut Face geometry is retained in debug.

For initially failed edge_ids only, the original convex hulls are
buffered successively by 1, 2, 3 and 4 metres. At each stage, remove
that larger hull from the remaining post-cut Faces, then retry the union.
A recovered edge_id is moved to regular output at the first successful
stage; the final debug shows the geometry after the last attempted cut.

At each successful buffer stage, the contiguous residual polygon is
ONLY a spatial selection geometry: match it against the valid ORIGINAL
native CGAL Faces of that same edge_id using positive-area overlap,
then union the selected UNCLIPPED original Faces for the regular output.
That restored output may be Polygon or MultiPolygon; never assign
ownership across edge_ids or accept a boundary-touch-only match.

For edge_ids already valid before the buffer loop, the previous
post-TURN_USE-cut Polygon output remains unchanged.

As a FINAL stage for edge_ids still in debug after the buffer attempts:
split residual MultiPolygons into polygon components; discard each
component strictly smaller than 250 square metres (EPSG:31256);
union the retained residual components of the same original edge_id
into Polygon or MultiPolygon for regular output. This final stage
DOES NOT restore original Faces. Unprocessable/null source Faces
remain explicitly diagnosed, rather than silently claimed as solved. If any source polygon is invalid, the union fails, or the
result is not a single valid Polygon, the entire edge_id is put into
a JSON failure report and ALL its post-cut Face geometries into a separate
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
from shapely.geometry import Polygon, MultiPolygon, mapping, shape
from shapely.ops import transform
from shapely.strtree import STRtree

from scripts.cgal_turn_use_hulls import load_turn_use_hulls
from scripts.wienwide_grid import load_aoi
from shapely.validation import explain_validity


SCHEMA="cgal-original-edge-id-turn-use-hull-dissolve-v6-final-debug-area-filter"


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


def _restore_original_faces(candidate,original_faces,to_wgs):
	"""Use a recovered residual ONLY to select native Faces of SAME edge_id.

	The original Faces are pre-TURN_USE (and pre-buffer) metric geometries.
	Require positive overlap area: mere common boundaries cannot select
	unrelated original Faces. No cross-edge_id joins, clipping, buffering,
	make_valid or spatial owner reassignment. MultiPolygon is allowed.
	"""
	if not isinstance(candidate,Polygon) or candidate.is_empty or not candidate.is_valid:
		raise ValueError("Wiederherstellung benötigt gültigen Polygon-Kandidaten")
	if not original_faces:
		raise ValueError("Keine ursprünglichen CGAL-Faces verfügbar")
	geoms=[geom for _,geom in original_faces]
	tree=STRtree(geoms)
	selected=[]
	matched_numbers=[]
	for i in tree.query(candidate,predicate="intersects"):
		number,original=original_faces[int(i)]
		if not isinstance(original,Polygon) or original.is_empty or not original.is_valid:
			raise ValueError(f"Face {number}: ursprüngliches Polygon ungültig")
		overlap=original.intersection(candidate)
		if overlap.area<=0:
			continue
		selected.append(original)
		matched_numbers.append(number)
	if not selected:
		raise ValueError("Kein ursprüngliches Polygon mit positiver Flächenüberschneidung")
	restored=union_all(selected)
	if not isinstance(restored,(Polygon,MultiPolygon)) or restored.is_empty or not restored.is_valid:
		raise ValueError("Vereinigte ursprüngliche Faces ergeben kein gültiges Polygon/MultiPolygon")
	wgs=transform(to_wgs,restored)
	if not isinstance(wgs,(Polygon,MultiPolygon)) or wgs.is_empty or not wgs.is_valid:
		raise ValueError("Ursprüngliche Faces ergeben kein gültiges WGS84 Polygon/MultiPolygon")
	return {
		"geometry":restored,
		"matched_face_numbers":sorted(matched_numbers),
		"matched_face_count":len(matched_numbers),
		"buffer_candidate_area_m2":candidate.area,
	}


def _retry_buffered_hulls(
		debug_surfaces,initial_reason,initial_detail,hull_geometries,
		buffer_cache,original_faces,to_wgs,stats):
	"""Progressively cut only FAILED edge_ids, in metric EPSG:31256.

	Each stage buffers the ORIGINAL convex hull by an absolute radius
	(1/2/3/4 metres), and differences the CURRENT residual geometries.
	This is not an additional 1+2+3+4 metre cumulative buffer.
	Source errors / cut failures cannot be turned into false successes:
	unavailable geometries stay null and block promotion to regular output.
	"""
	surfaces=list(debug_surfaces)
	# Do not allow an unprocessable Face to disappear from the
	# completeness check merely because other Faces can form a polygon.
	original_blocker=any(
		(geom is None and status!="fully_removed")
		or (geom is not None and not geom.is_empty and
			(not geom.is_valid or geom.geom_type not in ("Polygon","MultiPolygon")))
		for _,geom,status,_ in surfaces)
	reason=initial_reason
	detail=initial_detail
	attempted=[]
	for radius in range(1,5):
		if radius not in buffer_cache:
			buffered=[geom.buffer(radius) for geom in hull_geometries]
			if any(g.is_empty or not g.is_valid or
					g.geom_type not in ("Polygon","MultiPolygon")
					for g in buffered):
				raise ValueError(f"TURN_USE +{radius} m: ungültige Puffer-Hülle")
			buffer_cache[radius]=(buffered,STRtree(buffered))
		buffered,tree=buffer_cache[radius]
		attempted.append(radius)
		stats[f"buffer_{radius}m_attempted_edge_ids"]+=1
		next_surfaces=[]
		stage_error=None
		stage_detail=None
		for number,current,status,note in surfaces:
			if current is None or current.is_empty:
				next_surfaces.append((number,current,status,note))
				continue
			if not current.is_valid or current.geom_type not in (
					"Polygon","MultiPolygon"):
				if stage_error is None:
					stage_error="invalid_after_buffer"
					stage_detail=f"Face {number}: {explain_validity(current)}"
				next_surfaces.append((number,current,status,note))
				continue
			try:
				indices=tree.query(current,predicate="intersects")
				if not len(indices):
					next_surfaces.append((number,current,status,note))
					continue
				mask=union_all([buffered[int(i)] for i in indices])
				residual=current.difference(mask)
				if not residual.is_empty and (
						not residual.is_valid or residual.geom_type not in (
							"Polygon","MultiPolygon")):
					stage_error="invalid_after_buffer"
					stage_detail=(
						f"Face {number}, +{radius} m: "
						+explain_validity(residual))
					next_surfaces.append((number,residual,"buffer_invalid",
						stage_detail))
					continue
				removed=max(0.,current.area-residual.area)
				stats["buffer_removed_area_sum_m2"]+=removed
				if removed>1e-8:
					stats[f"buffer_{radius}m_cut_faces"]+=1
				if residual.is_empty:
					stats[f"buffer_{radius}m_fully_removed_faces"]+=1
					next_surfaces.append((number,residual,
						"fully_removed",f"TURN_USE +{radius} m"))
				elif removed>1e-8:
					next_surfaces.append((number,residual,
						"buffer_cut",f"TURN_USE +{radius} m"))
				else:
					next_surfaces.append((number,residual,status,note))
			except Exception as exc:
				# The current pre-cut geometry is NOT emitted as a
				# post-buffer geometry when the operation fails.
				msg=f"Face {number}, +{radius} m: {type(exc).__name__}: {exc}"
				if stage_error is None:
					stage_error="turn_use_buffer_cut_error"
					stage_detail=msg
				next_surfaces.append((number,None,"buffer_cut_failed",msg))
		surfaces=next_surfaces
		stage_blocker=original_blocker or any(
			(geom is None and status!="fully_removed")
			or (geom is not None and not geom.is_empty and
				(not geom.is_valid or geom.geom_type not in ("Polygon","MultiPolygon")))
			for _,geom,status,_ in surfaces)
		if stage_blocker:
			# Continue cutting the other Faces so final debug is
			# spatially correct. A failed cut must NEVER be silently
			# dropped from the completeness check in later attempts.
			if not original_blocker and stage_error is not None:
				reason=stage_error
				detail=stage_detail
			stats[f"buffer_{radius}m_still_debug"]+=1
			continue
		if stage_error is not None:
			reason=stage_error
			detail=stage_detail
			stats[f"buffer_{radius}m_still_debug"]+=1
			continue
		parts=[geom for _,geom,_,_ in surfaces
			if geom is not None and not geom.is_empty]
		try:
			merged=union_all(parts)
			if merged.is_empty:
				reason="empty_union"
				detail="TURN_USE-Puffer entfernte alle Restflächen"
			elif merged.geom_type=="MultiPolygon":
				reason="not_contiguous"
				detail=f"{len(merged.geoms)} getrennte Polygone nach +{radius} m"
			elif not isinstance(merged,Polygon):
				reason="union_not_polygon"
				detail=f"Union +{radius} m ergab {merged.geom_type}"
			elif not merged.is_valid:
				reason="invalid_union"
				detail=f"+{radius} m: {explain_validity(merged)}"
			else:
				wgs=transform(to_wgs,merged)
				if not isinstance(wgs,Polygon) or wgs.is_empty or not wgs.is_valid:
					reason="output_geometry_error"
					detail=f"+{radius} m: ungültiges WGS84-Polygon"
				else:
					# The buffered Polygon is a SELECTION FOOTPRINT only.
					# Restore the complete original Faces it overlaps, and
					# do not require their union to be contiguous.
					try:
						restored=_restore_original_faces(
							merged,original_faces,to_wgs)
					except Exception as exc:
						reason="original_face_restore_error"
						detail=f"+{radius} m: {type(exc).__name__}: {exc}"
					else:
						stats[f"buffer_{radius}m_recovered_edge_ids"]+=1
						return (surfaces,None,None,merged,radius,attempted,restored)
		except Exception as exc:
			reason="union_error"
			detail=f"+{radius} m: {type(exc).__name__}: {exc}"
		stats[f"buffer_{radius}m_still_debug"]+=1
	return surfaces,reason,detail,None,None,attempted,None


def _filter_final_debug_components(surfaces,to_wgs,*,minimum_area_m2=250):
	"""Select surviving post-cut POLYGON COMPONENTS by metric area.

	Works on the final 0-to-4m residual geometry of one edge_id.
	No rematching against original CGAL Faces here. Null source errors
	stay in debug; fully removed Faces stay as null audit records.
	"""
	if minimum_area_m2<=0:
		raise ValueError("Flächenschwelle muss positiv sein")
	kept=[]
	unprocessable=[]
	info={
		"threshold_m2":minimum_area_m2,
		"kept_components":0,
		"discarded_components":0,
		"discarded_area_m2":0.,
		"kept_area_sum_m2":0.,
		"unavailable_faces":0,
	}
	for number,geom,status,note in surfaces:
		if geom is None or geom.is_empty:
			unprocessable.append((number,None,status,note))
			if status!="fully_removed":
				info["unavailable_faces"]+=1
			continue
		if not isinstance(geom,(Polygon,MultiPolygon)) or not geom.is_valid:
			unprocessable.append((number,geom,status,note))
			info["unavailable_faces"]+=1
			continue
		pieces=(geom.geoms if isinstance(geom,MultiPolygon) else (geom,))
		selected=[]
		for piece in pieces:
			if piece.area<minimum_area_m2:
				info["discarded_components"]+=1
				info["discarded_area_m2"]+=piece.area
				continue
			selected.append(piece)
			info["kept_components"]+=1
			info["kept_area_sum_m2"]+=piece.area
		if selected:
			residual=selected[0] if len(selected)==1 else MultiPolygon(selected)
			kept.append((number,residual,status,note))
	info["kept_face_count"]=len(kept)
	remaining=kept+unprocessable
	if not kept:
		return None,remaining,info,"no_components_at_or_above_250m2"
	try:
		merged=union_all([geom for _,geom,_,_ in kept])
		if not isinstance(merged,(Polygon,MultiPolygon)) or merged.is_empty or not merged.is_valid:
			raise ValueError("Endvereinigung ergibt kein gültiges Polygon/MultiPolygon")
		wgs=transform(to_wgs,merged)
		if not isinstance(wgs,(Polygon,MultiPolygon)) or wgs.is_empty or not wgs.is_valid:
			raise ValueError("Endvereinigung ergibt kein gültiges WGS84 Polygon/MultiPolygon")
		info["result_geometry_type"]=merged.geom_type
		info["result_area_m2"]=merged.area
		info["unresolved_source_errors"]=any(
			geom is not None or status!="fully_removed"
			for _,geom,status,_ in unprocessable)
		# Geometrien in der regulären Ausgabe dürfen nicht zusätzlich
		# im Debug auftauchen. Nicht bearbeitbare Quellen bleiben dort.
		return merged,unprocessable,info,None
	except Exception as exc:
		info["union_error"]=f"{type(exc).__name__}: {exc}"
		return None,remaining,info,"final_debug_union_error"


def dissolve(preview,out,debug,report,*,progress=None,junction_hulls=None,
		junction_metadata=None,replace_existing=False):
	preview,out,debug,report=map(Path,(preview,out,debug,report))
	if not preview.is_file() or preview.is_symlink():
		raise FileNotFoundError(f"CGAL-Vorschau fehlt: {preview}")
	for target in (out,debug,report):
		if target.is_symlink():
			raise ValueError(f"Ausgabedatei darf kein Symlink sein: {target}")
		if target.exists() and not replace_existing:
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
	buffer_cache={}
	recovered_edge_ids=[]
	final_debug_salvaged=[]
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
					original_faces=[]
					area_sum=0.0
					types=Counter()
					fallback_count=0
					reason=None
					detail=None
					# Collect post-TURN_USE geometry for EVERY source Face,
					# including after a different Face in this edge_id
					# has already failed. Never put the pre-cut geometry
					# back into the debug output.
					debug_surfaces=[]
					for number,kind,fallback,raw in rows:
						types[kind]+=1
						fallback_count+=fallback
						debug_metric=None
						cut_status="not_processed"
						cut_note=None
						item_error=None
						item_detail=None
						try:
							feature=json.loads(raw)
							geometry=shape(feature["geometry"])
							if not isinstance(geometry,Polygon):
								item_error="source_not_polygon"
								item_detail=f"Face {number}: {geometry.geom_type}"
								cut_status="source_not_polygon"
								continue
							if geometry.is_empty or geometry.area<=0 or not geometry.is_valid:
								item_error="source_invalid_polygon"
								item_detail=f"Face {number}: {explain_validity(geometry)}"
								cut_status="source_invalid"
								continue
							metric=transform(to_metric,geometry)
							if not metric.is_valid or metric.is_empty or metric.area<=0:
								item_error="projection_invalid"
								item_detail=f"Face {number}: {explain_validity(metric)}"
								cut_status="projection_invalid"
								continue
							# Save only validated original Faces belonging
							# to THIS edge_id before any TURN_USE subtraction.
							original_faces.append((number,metric))
							debug_metric=metric
							cut_status="unchanged"
							# Historical TURN_USE convex junction cut, always
							# BEFORE union_all(parts) by original edge_id.
							if hull_tree is not None:
								try:
									indices=hull_tree.query(metric,predicate="intersects")
									if len(indices):
										local_mask=union_all([
											hull_geometries[int(i)] for i in indices])
										cut=metric.difference(local_mask)
										# Even a problematic cut geometry is
										# the ONLY correct candidate for debug.
										debug_metric=cut
										cut_status="cut"
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
											cut_status="fully_removed"
											continue
										metric=cut
								except Exception as exc:
									item_error="turn_use_cut_error"
									item_detail=f"Face {number}: {type(exc).__name__}: {exc}"
									# If difference itself raised before
									# producing a result, geometry is UNKNOWN.
									# Never show the uncut input as post-cut.
									if cut_status=="unchanged":
										debug_metric=None
										cut_status="cut_failed"
									else:
										cut_status="cut_invalid"
									cut_note=item_detail
									continue
							parts.append(metric)
							area_sum+=metric.area
						except Exception as exc:
							item_error="source_geometry_error"
							item_detail=f"Face {number}: {type(exc).__name__}: {exc}"
							debug_metric=None
							cut_status="source_error"
							cut_note=item_detail
						finally:
							debug_surfaces.append((
								number,debug_metric,cut_status,cut_note))
							if item_error is not None and reason is None:
								reason=item_error
								detail=item_detail
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
					# Only failed edge_ids are retried with 1–4 m
					# expanded TURN_USE convex hulls. The final residuals
					# replace the initial debug geometries.
					initial_reason=reason
					attempted=[]
					recovered_at_m=0
					restored_original=None
					if reason is not None and hull_tree is not None:
						stats["buffer_retry_edge_ids"]+=1
						(debug_surfaces,reason,detail,recovered_joined,
							recovered_radius,attempted,restored_original)=_retry_buffered_hulls(
							debug_surfaces,reason,detail,hull_geometries,
							buffer_cache,original_faces,to_wgs,stats)
						if recovered_radius is not None:
							# The valid residual is only used to MATCH originals.
							joined=restored_original["geometry"]
							recovered_at_m=recovered_radius
							area_sum=sum(geom.area for face_no,geom in original_faces
								if face_no in restored_original["matched_face_numbers"])
					if reason is None:
						try:
							wgs=transform(to_wgs,joined)
							if (not isinstance(wgs,(Polygon,MultiPolygon))
									or (recovered_at_m==0 and not isinstance(wgs,Polygon))
									or not wgs.is_valid or wgs.is_empty):
								raise ValueError(
									"Projektion liefert kein gültiges erlaubtes Polygon/MultiPolygon")
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
									"turn_use_hulls_removed":bool(hull_geometries),
									"turn_use_buffer_m":recovered_at_m,
									"recovered_by_buffer":recovered_at_m>0,
									"geometry_from_original_faces":recovered_at_m>0,
									"matched_original_face_count":(
										restored_original["matched_face_count"] if restored_original else 0),
									"buffer_candidate_area_m2":(
										restored_original["buffer_candidate_area_m2"] if restored_original else None)},
								"geometry":mapping(wgs)}
							first_good=_write_feature(good,new_feature,first_good)
							if restored_original is not None:
								recovered_edge_ids.append({
									"edge_id":edge_id,
									"buffer_m":recovered_at_m,
									"initial_reason":initial_reason,
									"result_geometry_type":joined.geom_type,
									"matched_original_face_numbers":restored_original["matched_face_numbers"],
									"candidate_area_m2":restored_original["buffer_candidate_area_m2"],
									"original_union_area_m2":joined.area})
								stats["restored_original_face_matches"]+=restored_original["matched_face_count"]
								if isinstance(joined,MultiPolygon):
									stats["restored_multipolygon_outputs"]+=1
							stats["merged_polygons"]+=1
							if isinstance(joined,MultiPolygon):
								stats["merged_multipolygon_features"]+=1
							stats["accepted_source_faces"]+=len(rows)
							accepted_fallbacks+=fallback_count
							stats["source_overlap_area_m2"]+=max(0,area_sum-joined.area)
						except Exception as exc:
							reason="output_geometry_error"
							detail=f"{type(exc).__name__}: {exc}"
					# Final stage: the remaining 0–4 m post-TURN_USE
					# DEBUG geometries, NOT the originals, are filtered
					# component by component in metric square metres.
					# MultiPolygon is expressly valid at this stage.
					final_filter_info=None
					final_area_salvaged=False
					if reason is not None:
						stats["final_debug_filter_attempted_edge_ids"]+=1
						(final_geom,filtered_debug,final_filter_info,
							final_filter_error)=_filter_final_debug_components(
							debug_surfaces,to_wgs,minimum_area_m2=250)
						debug_surfaces=filtered_debug
						stats["final_debug_discarded_components"]+=final_filter_info[
							"discarded_components"]
						stats["final_debug_discarded_area_m2"]+=final_filter_info[
							"discarded_area_m2"]
						stats["final_debug_retained_components"]+=final_filter_info[
							"kept_components"]
						if final_geom is not None:
							try:
								last_buffer=attempted[-1] if attempted else 0
								new_feature={
									"type":"Feature",
									"properties":{
										"edge_id":edge_id,
										"source_face_count":len(rows),
										"segment_face_count":types["segment"],
										"inner_point_face_count":types["inner_point"],
										"fallback_face_count":fallback_count,
										"area_m2":final_geom.area,
										"preview_based":True,
										"sis_clipped":False,
										"turn_use_hulls_removed":bool(hull_geometries),
										"turn_use_buffer_m":last_buffer,
										"recovered_by_buffer":False,
										"geometry_from_original_faces":False,
										"recovered_by_debug_area_filter":True,
										"debug_area_threshold_m2":250,
										"debug_kept_components":final_filter_info[
											"kept_components"],
										"debug_discarded_components":final_filter_info[
											"discarded_components"],
										"partial_source_errors":final_filter_info[
											"unresolved_source_errors"]},
									"geometry":mapping(transform(to_wgs,final_geom))}
								first_good=_write_feature(good,new_feature,first_good)
								stats["merged_polygons"]+=1
								if isinstance(final_geom,MultiPolygon):
									stats["merged_multipolygon_features"]+=1
								stats["final_debug_salvaged_edge_ids"]+=1
								stats["final_debug_salvaged_area_m2"]+=final_geom.area
								accepted_fallbacks+=fallback_count
								final_area_salvaged=True
								final_debug_salvaged.append({
									"edge_id":edge_id,
									"geometry_type":final_geom.geom_type,
									"area_m2":final_geom.area,
									"last_buffer_m":last_buffer,
									"previous_reason":reason,
									**final_filter_info})
							except Exception as exc:
								final_filter_error="final_debug_output_error"
								final_filter_info["output_error"]=(
									f"{type(exc).__name__}: {exc}")
								# Keep geometries available for debug,
								# never discard them after output failure.
								debug_surfaces=filtered_debug
						if not final_area_salvaged:
							stats["final_debug_unsalvaged_edge_ids"]+=1
							if final_filter_error:
								detail=(f"{detail}; final_debug_filter="
									f"{final_filter_error}: "
									f"{final_filter_info.get('union_error') or final_filter_info.get('output_error') or 'keine Fläche >=250 m²'}")
						elif not final_filter_info["unresolved_source_errors"]:
							# Fully removed audit-null entries may remain;
							# no unresolved geometry needs a debug feature.
							reason=None
							debug_surfaces=[]
					if reason is not None and debug_surfaces:
						if not final_area_salvaged:
							stats["rejected_edge_ids"]+=1

						if not final_area_salvaged:
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
							"initial_dissolve_reason":initial_reason,
							"buffer_attempts_m":attempted,
							"last_buffer_m":attempted[-1] if attempted else 0,
							"partially_salvaged_to_output":final_area_salvaged,
							"final_debug_filter":final_filter_info,
							"face_numbers":[number for number,_,_,_ in rows]})
						raw_by_number={number:raw for number,_,_,raw in rows}
						for number,post_cut,cut_status,cut_note in debug_surfaces:
							feature=json.loads(raw_by_number[number])
							props=dict(feature["properties"])
							props["dissolve_error"]=reason
							props["dissolve_error_detail"]=detail
							props["debug_after_turn_use"]=True
							props["turn_use_cut_status"]=cut_status
							props["turn_use_cut_note"]=cut_note
							props["last_turn_use_buffer_m"]=attempted[-1] if attempted else 0
							props["debug_area_threshold_m2"]=250
							props["partial_salvage_to_output"]=final_area_salvaged
							# A fully removed or unprocessable Face has no
							# remaining geometry. Keep its ID as an explicit
							# null-geometry audit record, not an uncut polygon.
							if post_cut is None or post_cut.is_empty:
								feature["geometry"]=None
								stats["debug_null_geometries"]+=1
							else:
								try:
									feature["geometry"]=mapping(
										transform(to_wgs,post_cut))
									stats["debug_post_cut_geometries"]+=1
								except Exception as exc:
									feature["geometry"]=None
									props["turn_use_cut_status"]="output_transform_failed"
									props["turn_use_cut_note"]=str(exc)
									stats["debug_null_geometries"]+=1
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
					'"turn_use_hull_cut_before_union":true,'
					'"failed_edges_buffered_m":[1,2,3,4],'
					'"buffer_recovered_output":"union_of_positive_area_matched_original_faces",'
					'"buffer_recovered_allows_multipolygon":true,'
					'"final_debug_area_min_m2":250,'
					'"final_debug_union_allows_multipolygon":true}}\n')
				bad.write('\n],"metadata":{"schema":"'+SCHEMA+'",'
					'"debug_post_turn_use_cut":true,'
					'"failed_edges_buffered_up_to_m":4,'
					'"final_debug_components_min_m2":250,'
					'"null_geometry_for_removed_or_unavailable_faces":true}}\n')
		overview={
			"schema":SCHEMA,
			"source_preview":str(preview),
			"turn_use_junctions":{
				"rule":"all_TURN_USE_vertices_convex_hull_by_via_node_id",
				"hull_count":len(hull_geometries),
				"applied_before_edge_id_union":True,
				"retry_buffers_m":[1,2,3,4],
				"buffer_radius_interpretation":"absolute_from_original_hull",
				"source":junction_metadata or {},
			},
			"merged_geojson":str(out),
			"debug_geojson":str(debug),
			"debug_geometry_semantics":"post_turn_use_cut; "
				"fully removed or not safely cut -> null geometry",
			"preview_based":True,
			"geometrically_assured":False,
			"sis_clipped":False,
			"source_face_counts":dict(sources),
			"statistics":dict(stats),
			"accepted_fallback_source_faces":accepted_fallbacks,
			"recovered_edge_ids":recovered_edge_ids,
			"final_debug_area_filter":{
				"min_component_area_m2":250,
				"discard_rule":"component_area_m2 < 250",
				"metric_crs":"EPSG:31256",
				"output_geometry_types":["Polygon","MultiPolygon"],
				"successful_edge_ids":final_debug_salvaged},
			"buffer_recovery_output":"uncut_original_native_faces_selected_by_positive_area_overlap_same_edge_id",
			"failures":failures,
		}
		(stage/"report.json").write_text(json.dumps(
			overview,ensure_ascii=False,indent=2,allow_nan=False)+"\n",
			encoding="utf-8")
		for temporary,output in (("merged.geojson",out),
				("debug.geojson",debug),("report.json",report)):
			os.replace(stage/temporary,output)
	print(f"CGAL-Dissolve: {stats['merged_polygons']:,} reguläre Flächen-Features, "
		f"{stats['rejected_edge_ids']:,} edge_ids mit Fehlern, "
		f"{len(recovered_edge_ids):,} per 1–4 m Puffer gerettet, "
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
	parser.add_argument("--replace-existing",action="store_true",
		help="Bestehende reguläre und Debug-Ausgaben erst nach erfolgreicher "
		"neuer Verarbeitung atomar ersetzen")
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
		replace_existing=args.replace_existing,
		progress=lambda message:print(message,flush=True))


if __name__=="__main__":
	main()
