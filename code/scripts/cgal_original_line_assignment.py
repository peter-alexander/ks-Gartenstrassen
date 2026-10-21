"""Attribute Voronoi faces using original LINEAR_USE/face intersections only.

Strict Shapely 'intersects' semantics are used: a boundary-point touch
counts as an intersection. No representative points, nearest-line
heuristics, or implicit assignment of ambiguous lines are permitted.
"""
from collections import defaultdict
import json
import os
from pathlib import Path
import tempfile

from shapely.geometry import mapping
from shapely.ops import transform
from shapely.strtree import STRtree


def assign_by_intersections(polygons,records):
	"""Return face labels and explicit, inspectable ambiguity diagnostics.

	records: (object_id, edge_id, original EPSG:31256 LineString).
	Each input line must intersect exactly one candidate polygon before it
	can propose its original edge_id for that polygon.
	"""
	tree=STRtree(polygons)
	proposals=defaultdict(lambda:defaultdict(set))
	touched=defaultdict(set)
	multiple=[]
	missing=[]
	unique_count=0
	point_only_multiple=0
	for line_index,(object_id,edge_id,line) in enumerate(records):
		if line.is_empty or not line.is_valid or line.length<=0:
			raise ValueError(f"LINEAR_USE {object_id}: ungültige Quelllinie")
		indices=sorted(int(i) for i in tree.query(line,predicate="intersects"))
		for i in indices:
			touched[i].add(line_index)
		if not indices:
			missing.append({"line_index":line_index,"object_id":object_id,
				"edge_id":edge_id})
		elif len(indices)>1:
			# Boundary-only contacts can trigger multiple hits, even where
			# only one polygon contains a positive-length portion of the line.
			# Diagnose this, but never silently discard those intersections.
			length_hits=sum(
				line.intersection(polygons[i]).length>0 for i in indices)
			if length_hits<=1:
				point_only_multiple+=1
			multiple.append({"line_index":line_index,
				"object_id":object_id,"edge_id":edge_id,
				"polygon_indices":indices,
				"positive_length_hits":length_hits,
				"boundary_only_hits":len(indices)-length_hits})
		else:
			unique_count+=1
			proposals[indices[0]][edge_id].add(object_id)
	labels=[]
	conflicts=[]
	unassigned=[]
	for i in range(len(polygons)):
		choices=proposals.get(i,{})
		if len(choices)==1:
			labels.append(next(iter(choices)))
		elif len(choices)>1:
			labels.append(None)
			conflicts.append({"polygon_index":i,
				"edge_ids":sorted(choices),
				"object_ids":sorted(set().union(*choices.values()))})
			unassigned.append({"polygon_index":i,
				"reason":"conflicting_edge_ids",
				"intersecting_lines":len(touched.get(i,()))})
		else:
			labels.append(None)
			unassigned.append({"polygon_index":i,
				"reason":"no_unique_source_line",
				"intersecting_lines":len(touched.get(i,()))})
	report={"schema":"original-line-polygon-intersections-v1",
		"line_count":len(records),"polygon_count":len(polygons),
		"lines_exactly_one_polygon":unique_count,
		"lines_multiple_polygons":len(multiple),
		"lines_no_polygon":len(missing),
		"multiple_from_boundary_contacts_only":point_only_multiple,
		"polygons_conflicting_edge_ids":len(conflicts),
		"polygons_without_unambiguous_edge_id":len(unassigned),
		"polygons_unambiguously_assigned":len(polygons)-len(unassigned),
		"intersection_rule":"Shapely intersects; boundary-point contacts count",
		"fallback_assignment":False}
	return {"labels":labels,"multiple":multiple,"missing":missing,
		"conflicts":conflicts,"unassigned":unassigned,"report":report}


def diagnostic_paths(output):
	out=Path(output)
	stem=out.stem
	return {
		"multiple":out.with_name(stem+"__linien_mehrere_flaechen.geojson"),
		"missing":out.with_name(stem+"__linien_ohne_flaeche.geojson"),
		"conflicts":out.with_name(stem+"__flaechen_edge_id_konflikt.geojson"),
		"unassigned":out.with_name(stem+"__flaechen_ohne_eindeutige_edge_id.geojson"),
		"report":out.with_name(stem+"__zuordnungsbericht.json")}


def write_diagnostics(output,polygons,records,result,to_wgs):
	"""Save four independent map layers and counts without changing inputs."""
	paths=diagnostic_paths(output)
	for path in paths.values():
		if path.exists() or path.is_symlink():
			raise FileExistsError(f"Diagnose-Datei vorhanden: {path}")
	def features(kind):
		if kind in ("multiple","missing"):
			for item in result[kind]:
				object_id,edge_id,line=records[item["line_index"]]
				props={key:value for key,value in item.items()
					if key!="line_index"}
				yield {"type":"Feature","properties":props,
					"geometry":mapping(transform(to_wgs,line))}
		else:
			for item in result[kind]:
				index=item["polygon_index"]
				props=dict(item)
				yield {"type":"Feature","properties":props,
					"geometry":mapping(transform(to_wgs,polygons[index]))}
	# All outputs are staged first. No old artifact is silently overwritten.
	staged={}
	try:
		for kind,path in paths.items():
			path.parent.mkdir(parents=True,exist_ok=True)
			with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",
					dir=path.parent,prefix=path.name+".",suffix=".tmp",
					delete=False) as handle:
				staged[kind]=Path(handle.name)
				if kind=="report":
					json.dump(result["report"],handle,ensure_ascii=False,
						indent=2,allow_nan=False)
				else:
					handle.write('{"type":"FeatureCollection","features":[')
					for i,feature in enumerate(features(kind)):
						if i:
							handle.write(",\n")
						handle.write(json.dumps(feature,ensure_ascii=False,
							separators=(",",":"),allow_nan=False))
					handle.write("]}")
				handle.write("\n")
		for kind,path in paths.items():
			os.replace(staged.pop(kind),path)
	finally:
		for stage in staged.values():
			stage.unlink(missing_ok=True)
	return paths
