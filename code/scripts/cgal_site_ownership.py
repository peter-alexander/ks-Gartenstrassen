"""Recover CGAL segment-site ownership before any SIS clipping.

The C++ exporter emits each finite CGAL vertex's actual site plus its
supporting input segment. A segment site can be linked to the original
LINEAR_USE edge_id using the *exact* supporting segment, not an invented
sampling point. Point sites are deliberately not attributed.
"""
import json
import math
from pathlib import Path
from collections import defaultdict

from shapely.geometry import LineString
from shapely.strtree import STRtree

from scripts.cgal_segment_input import SCALE


def _integral_coordinate(value):
	n=int(round(value))
	if not math.isfinite(value) or abs(value-n)>1e-5:
		raise ValueError(f"CGAL supporting site is not on integer millimetre grid: {value}")
	return n


def read_sites(path,owners,origin):
	"""Read native CGAL sites; supporting segments must map to real inputs."""
	ox,oy=origin
	segments=[]
	points=0
	frame_segments=0
	input_sites=0
	with Path(path).open(encoding="utf-8") as stream:
		for number,raw in enumerate(stream,1):
			fields=raw.split()
			if not fields:
				continue
			if fields[0]=="P" and len(fields)==3:
				coords=[float(x) for x in fields[1:]]
				if not all(math.isfinite(x) for x in coords):
					raise ValueError(f"CGAL site line {number}: invalid point")
				points+=1
				continue
			if fields[0]!="S" or len(fields)!=9:
				raise ValueError(f"CGAL site line {number}: unexpected format")
			vals=[float(x) for x in fields[1:]]
			if not all(math.isfinite(x) for x in vals):
				raise ValueError(f"CGAL site line {number}: non-finite segment")
			a=tuple(_integral_coordinate(x) for x in vals[:2])
			b=tuple(_integral_coordinate(x) for x in vals[2:4])
			key=tuple(sorted((a,b)))
			if key not in owners:
				# The artificial outer frame is deliberately not LINEAR_USE.
				frame_segments+=1
				continue
			c=(vals[4]/SCALE+ox,vals[5]/SCALE+oy)
			d=(vals[6]/SCALE+ox,vals[7]/SCALE+oy)
			if c==d:
				raise ValueError(f"CGAL site line {number}: zero length segment site")
			site=LineString((c,d))
			if not site.is_valid:
				raise ValueError(f"CGAL site line {number}: invalid segment")
			segments.append((number,owners[key],site))
			input_sites+=1
	return segments,{
		"native_segment_sites":input_sites,
		"native_point_sites_omitted":points,
		"outer_frame_segment_sites_omitted":frame_segments,
	}


def attribute_faces(faces,site_segments,site_stats):
	"""Attribute only polygons containing positive length of a CGAL segment site.

	No source-line 1:1 assumption. Many distinct segment sites of the same
	edge_id may legitimately contribute to one reconstructed polygon.
	Sites touching two polygon interiors, conflicts between distinct
	edge_ids and sites with no face are hard errors, not guessed away.
	"""
	tree=STRtree(faces)
	candidates=defaultdict(set)
	errors=[]
	polygon_sites=defaultdict(int)
	for site_number,edge_id,segment in site_segments:
		matches=tree.query(segment,predicate="intersects")
		positive=[]
		for idx in matches:
			idx=int(idx)
			length=segment.intersection(faces[idx]).length
			if length>1e-8:
				positive.append(idx)
		if len(positive)!=1:
			if len(errors)<30:
				errors.append({"site_line":site_number,"edge_id":edge_id,
					"reason":"site_crosses_multiple_faces" if positive
					else "site_has_no_face",
					"positive_faces":len(positive)})
			continue
		idx=positive[0]
		candidates[idx].add(edge_id)
		polygon_sites[idx]+=1
	labels=[]
	conflicts=0
	for idx in range(len(faces)):
		possible=candidates.get(idx,set())
		if len(possible)>1:
			conflicts+=1
			if len(errors)<30:
				errors.append({"polygon_index":idx,
					"reason":"conflicting_segment_owners",
					"edge_ids":sorted(possible)})
		labels.append(next(iter(possible)) if len(possible)==1 else None)
	stats=dict(site_stats)
	stats.update({
		"candidate_polygons":len(faces),
		"polygons_with_segment_edge_id":sum(label is not None for label in labels),
		"polygons_without_segment_edge_id":sum(label is None for label in labels),
		"segment_sites_without_unique_face":sum(
			item["reason"] in ("site_has_no_face","site_crosses_multiple_faces")
			for item in errors),
		"polygons_with_conflicting_segment_edge_id":conflicts,
		"attribution":"native_cgal_segment_sites_supporting_input",
		"point_site_attribution":False,
		"provenance_errors":errors})
	# The first list is bounded; separately track all failed sites.
	# A missing or split segment site must never be silently accepted.
	return labels,stats


def require_sound_attribution(stats):
	if stats["segment_sites_without_unique_face"] or stats[
			"polygons_with_conflicting_segment_edge_id"]:
		raise ValueError("CGAL-Segment-Site-Zuordnung ist nicht eindeutig: "
			+json.dumps(stats["provenance_errors"][:5],ensure_ascii=False))
