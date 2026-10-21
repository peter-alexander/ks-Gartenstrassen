"""Read-only finite distance comparison for segment blockers of unresolved cells."""
from shapely.geometry import box
from scripts.cgal_unresolved_site_audit import _metric_site


def audit_segment_blocker_witnesses(polygons,labels,candidates,bounds,*,scale=1000.,tolerance=1e-8):
	if len(polygons)!=len(labels) or scale<=0 or tolerance<0:
		raise ValueError("Invalid segment blocker audit")
	by_face={row["face_index"]:row for row in candidates
		if row.get("status")=="candidate_only_not_proven"}
	report=[]
	for row in bounds:
		fid=row["face_index"]
		if fid<0 or fid>=len(polygons) or labels[fid] is not None or fid not in by_face:
			raise ValueError("Expected unresolved candidate face")
		c=by_face[fid]["candidate_site"]
		if c["kind"]!="S":
			raise ValueError("Expected segment candidate")
		coords=tuple(c["coordinates"])
		segment=_metric_site(("S",coords),scale)
		observations=[]
		for tile in row.get("unknown_tile_examples",[]):
			site=tile["limiting_site"]
			if site["kind"]!="S":
				continue
			other_coords=tuple(site["coordinates"])
			other=_metric_site(("S",other_coords),scale)
			shared=set((coords[:2],coords[2:])) & set((other_coords[:2],other_coords[2:]))
			part=polygons[fid].intersection(box(*tile["bounds_m"]))
			if part.is_empty or part.area<=0:
				continue
			pt=part.representative_point()
			if not part.contains(pt) or not polygons[fid].contains(pt):
				continue
			gap=pt.distance(other)-pt.distance(segment)
			observations.append({"point_m":[pt.x,pt.y],
				"limiting_site":site,"shared_endpoint_count":len(shared),
				"competitor_minus_candidate_m":gap,
				"strict_counterexample":gap < -tolerance,
				"distance_tie":abs(gap)<=tolerance})
		report.append({"face_index":fid,"segment_blocker_samples":observations,
			"strict_counterexample_count":sum(x["strict_counterexample"] for x in observations),
			"status":"finite_segment_blocker_samples_only",
			"ownership_proven":False})
	return report
