"""Read-only native ray direction inventory for degenerate endpoint duals.

The R records contain an origin and second point. Their direction is
recorded but not interpreted as a Voronoi side or generator ownership.
"""
import math


def audit_endpoint_dual_ray_directions(alignment_groups,rays):
	reports=[]
	for group in alignment_groups:
		links=group.get("ordered_links",[])
		valid=(group.get("status")=="native_cw_ccw_cycle_alignment_only"
			and group.get("voronoi_side_proven") is False
			and group.get("ownership_proven") is False
			and len(links)==3 and len({row.get("edge_id") for row in links})==3)
		evidence=[]
		missing=[]
		if valid:
			for link in links:
				eid=link["edge_id"]
				records=rays.get(eid,[])
				if len(records)!=1 or len(records[0])!=4:
					missing.append(eid)
					valid=False
					continue
				try:
					x0,y0,x1,y1=[float(v) for v in records[0]]
				except (ValueError,TypeError):
					valid=False
					break
				dx,dy=x1-x0,y1-y0
				if not all(math.isfinite(v) for v in (x0,y0,x1,y1,dx,dy)) or dx==dy==0:
					valid=False
					break
				evidence.append({"edge_id":eid,"ray_origin":[x0,y0],
					"ray_direction":[dx,dy],
					"cycle_forward_matches_export":link["cycle_forward_matches_export"]})
		reports.append({"edge_ids":group.get("edge_ids",[]),
			"status":"native_endpoint_ray_directions_recorded_only" if valid
				else "blocked_endpoint_ray_direction_evidence",
			"rays":evidence,
			"missing_ray_edge_ids":missing,
			"voronoi_side_proven":False,"ownership_proven":False})
	return reports
