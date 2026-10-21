"""Read-only audit of native CW/CCW site records on endpoint duals.

CW and CCW describe the native export convention. They do not establish
the physical left/right side of a degenerate Voronoi dual.
"""
from scripts.cgal_endpoint_cycle_site_pairs import _site_key


def audit_endpoint_cw_ccw_pairs(stars,cycle_duals,topology_lines,edges):
	by_edge={eid:pair for eid,pair,_ in edges}
	results=[]
	for star,dual in zip(stars,cycle_duals):
		links=dual.get("cycle_links",[])
		ids={r["edge_id"] for r in star.get("incident_edges",[])}
		valid=(star.get("status")=="native_incident_star_unordered_only"
			and dual.get("status")=="native_cycle_dual_incidence_only"
			and star.get("ownership_proven") is False
			and dual.get("ownership_proven") is False
			and dual.get("voronoi_side_proven") is False
			and len(ids)==3 and len(links)==4
			and {r.get("edge_id") for r in links if r.get("edge_id") is not None}==ids)
		observed=[]
		if valid:
			for eid in sorted(ids):
				if (eid not in by_edge or type(eid) is not int
					or eid<0 or eid>=len(topology_lines)):
					valid=False
					break
				line=topology_lines[eid]
				prefix=f"T {eid} 1 CW "
				if not line.startswith(prefix) or " | CCW " not in line:
					valid=False
					break
				cw,ccw=line[len(prefix):].split(" | CCW ",1)
				try:
					sites=[_site_key(x) for x in (cw,ccw)]
				except (ValueError,TypeError):
					valid=False
					break
				if len(set(sites))!=2 or set(sites)!=set(by_edge[eid]):
					valid=False
					break
				observed.append({"edge_id":eid,"cw_site":list(sites[0]),
					"ccw_site":list(sites[1])})
		results.append({"edge_ids":star.get("edge_ids",[]),
			"status":"native_endpoint_cw_ccw_pair_recorded_only" if valid
				else "blocked_endpoint_cw_ccw_pair_mismatch",
			"native_pairs":observed if valid else [],
			"voronoi_side_proven":False,"ownership_proven":False})
	return results
