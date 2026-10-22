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

from shapely.geometry import LineString, mapping
from shapely.ops import transform
import os
import tempfile
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


def attribute_faces(faces,site_segments,site_stats,*,window=None):
	"""Attribute polygons whose INTERIOR contains positive length of a CGAL site.

	No source-line 1:1 assumption. Many distinct segment sites of the same
	edge_id may legitimately contribute to one reconstructed polygon.
	Sites touching two polygon interiors, conflicts between distinct
	edge_ids and sites with no face are hard errors, not guessed away.
	"""
	tree=STRtree(faces)
	candidates=defaultdict(set)
	errors=[]
	failed_segment_sites=0
	off_window_segment_sites=0
	boundary_only_contacts=0
	sites_with_boundary_contacts=0
	sites_with_multiple_interior_faces=0
	sites_only_on_boundaries=0
	polygon_sites=defaultdict(int)
	for site_number,edge_id,segment in site_segments:
		# A source LINEAR_USE polyline can extend beyond the Vienna AOI.
		# Sites wholly outside the clipped Voronoi window have no
		# generator line inside the polygonized domain.
		if window is not None and segment.intersection(window).length<=1e-8:
			off_window_segment_sites+=1
			continue
		matches=tree.query(segment,predicate="intersects")
		interior=[]
		boundary=[]
		for index in matches:
			idx=int(index)
			# DE-9IM first position: segment interior ∩ polygon interior.
			# Dimension 1 means a *positive-length* segment lies inside
			# the polygon. Geometric intersection length also includes
			# segments lying entirely along a polygon boundary.
			if segment.relate_pattern(faces[idx],"1********"):
				interior.append(idx)
			elif segment.intersection(faces[idx]).length>1e-8:
				boundary.append(idx)
		if boundary:
			sites_with_boundary_contacts+=1
			boundary_only_contacts+=len(boundary)
		if len(interior)!=1:
			failed_segment_sites+=1
			if len(interior)>1:
				sites_with_multiple_interior_faces+=1
			if not interior and boundary:
				sites_only_on_boundaries+=1
			if len(errors)<30:
				errors.append({"site_line":site_number,"edge_id":edge_id,
					"reason":"site_crosses_multiple_face_interiors"
						if len(interior)>1 else
						"site_only_on_face_boundaries" if boundary else
						"site_has_no_face",
					"interior_face_indices":sorted(interior),
					"boundary_face_indices":sorted(boundary),
					"interior_faces":len(interior),
					"boundary_faces":len(boundary)})
			continue
		idx=interior[0]
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
		"segment_sites_outside_window":off_window_segment_sites,
		"polygons_with_segment_edge_id":sum(label is not None for label in labels),
		"polygons_without_segment_edge_id":sum(label is None for label in labels),
		"segment_sites_without_unique_face":failed_segment_sites,
		"sites_with_multiple_face_interiors":sites_with_multiple_interior_faces,
		"sites_only_on_face_boundaries":sites_only_on_boundaries,
		"sites_with_boundary_contacts":sites_with_boundary_contacts,
		"ignored_boundary_only_intersections":boundary_only_contacts,
		"polygons_with_conflicting_segment_edge_id":conflicts,
		"attribution":"native_cgal_segment_sites_polygon_interior_de9im",
		"point_site_attribution":False,
		"provenance_errors":errors})
	# The diagnostic examples are bounded, but all failures are counted.
	# A missing or split segment site must never be silently accepted.
	return labels,stats


def require_sound_attribution(stats):
	if stats["segment_sites_without_unique_face"] or stats[
			"polygons_with_conflicting_segment_edge_id"]:
		raise ValueError("CGAL-Segment-Site-Zuordnung ist nicht eindeutig: "
			+json.dumps(stats["provenance_errors"][:5],ensure_ascii=False))


def write_site_diagnostics(output,faces,sites,stats,to_wgs):
	"""Preserve inspectable native-site failures before rejecting the run.

	Only the bounded example set is exported; counts are complete.
	This output is independent of SIS, and never overwrites older files.
	"""
	path=Path(output)
	report=path.with_name(path.stem+"__site_zuordnung.json")
	geojson=path.with_name(path.stem+"__site_konflikte.geojson")
	for target in (report,geojson):
		if target.exists() or target.is_symlink():
			raise FileExistsError(f"CGAL-Site-Diagnose bereits vorhanden: {target}")
	by_line={line:(edge_id,geom) for line,edge_id,geom in sites}
	features=[]
	for error in stats["provenance_errors"]:
		num=error.get("site_line")
		if num is not None and num in by_line:
			edge_id,segment=by_line[num]
			features.append({"type":"Feature",
				"properties":{"kind":"segment_site","site_line":num,
					"edge_id":edge_id,"reason":error["reason"],
					"interior_faces":error.get("interior_faces",0),
					"boundary_faces":error.get("boundary_faces",0)},
				"geometry":mapping(transform(to_wgs,segment))})
			for status,key in (
					("interior","interior_face_indices"),
					("boundary","boundary_face_indices")):
				for idx in error.get(key,[])[:12]:
					features.append({"type":"Feature",
						"properties":{"kind":"polygon_face",
							"site_line":num,"polygon_index":idx,
							"site_relation":status},
						"geometry":mapping(transform(to_wgs,faces[idx]))})
		elif "polygon_index" in error:
			idx=error["polygon_index"]
			features.append({"type":"Feature",
				"properties":{"kind":"polygon_conflict",
					"polygon_index":idx,
					"edge_ids":error["edge_ids"]},
				"geometry":mapping(transform(to_wgs,faces[idx]))})
	diagnostic={"type":"FeatureCollection","features":features}
	staged={}
	try:
		for target,document in ((report,stats),(geojson,diagnostic)):
			target.parent.mkdir(parents=True,exist_ok=True)
			with tempfile.NamedTemporaryFile(
					mode="w",encoding="utf-8",dir=target.parent,
					prefix=target.name+".",suffix=".tmp",delete=False) as handle:
				staged[target]=Path(handle.name)
				json.dump(document,handle,ensure_ascii=False,
					indent=2 if target==report else None,allow_nan=False)
				handle.write("\n")
		for target in (report,geojson):
			os.replace(staged.pop(target),target)
	finally:
		for tmp in staged.values():
			tmp.unlink(missing_ok=True)
	return report,geojson
