"""Read-only original CGAL dual primitive inventory for native endpoint E IDs.

S/R/L records describe native exported geometry. Even a nonzero segment
vector does not prove Voronoi left/right sides or cell ownership.
"""
import math


def audit_endpoint_dual_primitives(stars,ray_reports,edges):
	by_edge={eid:fragments for eid,_,fragments in edges}
	if len(stars)!=len(ray_reports):
		raise ValueError("Mismatched endpoint star and ray groups")
	results=[]
	for star,rays in zip(stars,ray_reports):
		ids={edge["edge_id"] for edge in star.get("incident_edges",[])}
		valid=(star.get("status")=="native_incident_star_unordered_only"
			and rays.get("status") in ("native_endpoint_ray_directions_recorded_only",
				"blocked_endpoint_ray_direction_evidence")
			and star.get("ownership_proven") is False
			and rays.get("ownership_proven") is False
			and rays.get("voronoi_side_proven") is False
			and len(ids)==3)
		records=[]
		if valid:
			for eid in sorted(ids):
				fragments=by_edge.get(eid)
				if fragments is None or not fragments:
					valid=False
					break
				primitives=[]
				for kind,values in fragments:
					if kind not in ("S","R","L") or len(values)!=4:
						valid=False
						break
					try:
						x0,y0,x1,y1=[float(v) for v in values]
					except (TypeError,ValueError):
						valid=False
						break
					if not all(math.isfinite(v) for v in (x0,y0,x1,y1)):
						valid=False
						break
					primitives.append({"kind":kind,"coordinates":[x0,y0,x1,y1]})
				if not valid:
					break
				records.append({"edge_id":eid,"primitives":primitives})
		results.append({"edge_ids":star.get("edge_ids",[]),
			"status":"native_endpoint_dual_primitives_recorded_only" if valid
				else "blocked_endpoint_dual_primitive_evidence",
			"edge_primitives":records if valid else [],
			"voronoi_side_proven":False,"ownership_proven":False})
	return results
