"""Match native point-star edge sites to independently verified cycle sites.

Only compares original CGAL site incidences, never Voronoi-cell ownership.
"""


def _site_key(site):
	kind=site.get("kind")
	coords=site.get("coordinates")
	if kind not in ("P","S") or not isinstance(coords,list) or len(coords)!=(2 if kind=="P" else 4):
		raise ValueError("Malformed native edge site")
	return (kind,*(float(x) for x in coords))


def audit_cycle_edge_site_match(stars,cycle_sites):
	if len(stars)!=len(cycle_sites):
		raise ValueError("Different native star/site-cycle counts")
	results=[]
	for star,cycle in zip(stars,cycle_sites):
		edges=star.get("incident_edges",[])
		links=cycle.get("adjacent_face_sites",[])
		valid=(star.get("status")=="native_incident_star_unordered_only"
			and cycle.get("status")=="native_cycle_shared_sites_verified_only"
			and star.get("ownership_proven") is False
			and cycle.get("ownership_proven") is False
			and cycle.get("cyclic_order_proven") is True
			and set(star.get("edge_ids",[]))==set(cycle.get("edge_ids",[]))
			and len(edges)==3 and len(links)==4)
		matched=[]
		if valid:
			try:
				other={edge["edge_id"]:_site_key(edge["other_sites"][0])
					for edge in edges if len(edge["other_sites"])==1}
				seen=[tuple(link["shared_other_site"]) for link in links]
				finite=[s for s in seen if s!=("INF",)]
				valid=(len(other)==3 and len(set(other.values()))==3
					and len(finite)==3 and len(set(finite))==3
					and seen.count(("INF",))==1 and set(finite)==set(other.values()))
				if valid:
					matched=[{"edge_id":eid,"site":list(site)} for eid,site in sorted(other.items())]
			except (KeyError,TypeError,ValueError,IndexError):
				valid=False
		results.append({"edge_ids":list(star.get("edge_ids",[])),
			"status":"native_cycle_edge_sites_identical_only" if valid
				else "blocked_cycle_edge_site_disagreement",
			"matched_edges":matched if valid else [],
			"cyclic_order_proven":bool(valid),"ownership_proven":False})
	return results
