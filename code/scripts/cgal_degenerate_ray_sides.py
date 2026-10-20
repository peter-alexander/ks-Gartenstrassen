"""Read-only geometric side audit for coincident CGAL rays at segment endpoints.

Cross products describe where input sites lie relative to the directed
shared boundary; this is NOT a cell ownership rule.
"""
from scripts.cgal_unresolved_site_audit import _metric_site


def audit_degenerate_ray_sides(native_source_rows,*,scale=1000.,tolerance=1e-8):
	result=[]
	for row in native_source_rows:
		records=row["overlapping_native_sources"]
		if len(records)!=2 or any(r["fragment_kind"]!="R" for r in records):
			continue
		sites=[{(s["kind"],tuple(s["coordinates"])) for s in r["sites"]}
			for r in records]
		shared=sites[0]&sites[1]
		others=[s-shared for s in sites]
		if len(shared)!=1 or any(len(x)!=1 for x in others):
			continue
		point=next(iter(shared))
		if point[0]!="P":
			continue
		left,right=[next(iter(x)) for x in others]
		if left[0]!="S" or right[0]!="S":
			continue
		bounds=records[0]["clipped_bounds"]
		if bounds!=records[1]["clipped_bounds"]:
			continue
		x0,y0,x1,y1=bounds
		if abs(x1-x0)>tolerance and abs(y1-y0)>tolerance:
			continue
		# Direction here is deterministic for reporting, not native ray
		# orientation. The native E record does not encode ownership side.
		start=(x0,y0)
		end=(x1,y1)
		dx=end[0]-start[0]
		dy=end[1]-start[1]
		def sign(site):
			geom=_metric_site(site,scale)
			coords=list(geom.coords) if site[0]=="S" else [(geom.x,geom.y)]
			values=[dx*(p[1]-start[1])-dy*(p[0]-start[0])
				for p in coords]
			return ["left" if v>tolerance else
				"right" if v< -tolerance else "on_line" for v in values]
		result.append({"face_indices":row["face_indices"],
			"native_edge_ids":[r["edge_id"] for r in records],
			"common_point":{"kind":point[0],"coordinates":list(point[1])},
			"segments":[{"site":{"kind":s[0],"coordinates":list(s[1])},
				"endpoint_sides":sign(s)} for s in (left,right)],
			"report_direction":[list(start),list(end)],
			"shared_segment_bounds_equal":True})
	return result
