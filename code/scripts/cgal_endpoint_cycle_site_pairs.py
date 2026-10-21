"""Read-only verification of native triangle sites on a complete point-star cycle.

Every adjacent pair of Delaunay triangles must share precisely the point
site and one other original vertex site. No Voronoi owner is assigned.
"""
import math
from scripts.cgal_endpoint_vertex_slots import _site_slots


def _site_key(site):
	parts=site.split()
	if parts==["INF"]:
		return ("INF",)
	if len(parts) not in (3,5) or parts[0] not in ("P","S") or (parts[0]=="P")!=(len(parts)==3):
		raise ValueError("Malformed native vertex site")
	values=tuple(float(x) for x in parts[1:])
	if not all(math.isfinite(x) for x in values):
		raise ValueError("Nonfinite native vertex site")
	return (parts[0],*values)


def audit_endpoint_cycle_site_pairs(stars,cycles,face_pairs,face_vertices):
	reports=[]
	for star,cycle in zip(stars,cycles):
		point=star.get("point_site",{})
		coords=point.get("coordinates",[])
		path=cycle.get("face_cycle",[])
		valid=(star.get("status")=="native_incident_star_unordered_only"
			and cycle.get("status")=="complete_native_face_cycle_only"
			and star.get("ownership_proven") is False
			and cycle.get("ownership_proven") is False
			and cycle.get("cyclic_order_proven") is True
			and point.get("kind")=="P" and len(coords)==2
			and len(path)==4 and len(set(path))==4)
		sites={}
		if valid:
			for edge in star["incident_edges"]:
				eid=edge["edge_id"]
				pair=face_pairs.get(eid)
				vertices=face_vertices.get(eid)
				if pair is None or vertices is None:
					valid=False
					break
				ids=[pair["face_id"],pair["neighbor_face_id"]]
				if vertices.get("face_ids")!=ids:
					valid=False
					break
				for fid,raw in zip(ids,vertices["raw_slots"]):
					try:
						three=[_site_key(site) for site in _site_slots(raw)]
					except (ValueError,TypeError):
						valid=False
						break
					if (len(set(three))!=3 or (fid in sites and sites[fid]!=three)):
						valid=False
						break
					sites[fid]=three
				if not valid:
					break
			valid=valid and set(path)==set(sites)
		links=[]
		if valid:
			central=("P",*(float(x) for x in coords))
			for a,b in zip(path,path[1:]+path[:1]):
				common=set(sites[a]).intersection(sites[b])
				if central not in common or len(common)!=2:
					valid=False
					break
				other=next(x for x in common if x!=central)
				links.append({"face_ids":[a,b],"shared_other_site":other})
		reports.append({"edge_ids":star.get("edge_ids",[]),
			"status":"native_cycle_shared_sites_verified_only" if valid
				else "blocked_cycle_shared_site_mismatch",
			"adjacent_face_sites":links if valid else [],
			"cyclic_order_proven":bool(valid),"ownership_proven":False})
	return reports
