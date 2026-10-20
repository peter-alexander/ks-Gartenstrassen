"""Read-only diagnostics for candidate CGAL subface/site incompatibilities.

Compare generator geometry with candidate polygons and report native
labelled dual fragments near each inconsistent polygon boundary.
This is not a replacement or an alternative ownership heuristic.
"""
from shapely.geometry import LineString
from shapely.strtree import STRtree

from scripts.cgal_unresolved_site_audit import _metric_site


def incompatible_candidates(candidates,labelled_segments,*,scale=1000.,limit=12):
	lines=[line for line,_ in labelled_segments]
	tree=STRtree(lines) if lines else None
	mismatches=[]
	for index,(face,site) in enumerate(candidates):
		if site is None:
			continue
		geometry=_metric_site(site,scale)
		if face.intersects(geometry):
			continue
		records=[]
		for hit in (tree.query(face.boundary) if tree is not None else []):
			i=int(hit)
			line,pair=labelled_segments[i]
			if not line.intersects(face.boundary):
				continue
			records.append({
				"source_index":i,
				"generator_pair":[{"kind":s[0],"coordinates":list(s[1])}
					for s in pair],
				"contains_claimed_site":site in pair,
				"boundary_distance_m":line.distance(face.boundary),
				"boundary_overlap_m":line.intersection(face.boundary).length})
		records.sort(key=lambda r:(-r["boundary_overlap_m"],r["source_index"]))
		mismatches.append({
			"candidate_index":index,
			"face_area_m2":face.area,
			"face_bounds":list(face.bounds),
			"claimed_site":{"kind":site[0],"coordinates":list(site[1])},
			"site_distance_m":face.distance(geometry),
			"site_bounds":list(geometry.bounds),
			"site_kind":geometry.geom_type,
			"intersecting_dual_count":len(records),
			"claimed_site_boundary_records":sum(
				r["contains_claimed_site"] for r in records),
			"incident_duals":records[:limit]})
	return mismatches
