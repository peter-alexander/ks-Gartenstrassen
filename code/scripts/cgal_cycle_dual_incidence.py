"""Read-only bridge from oriented native primal face-cycle links to dual E IDs.

The infinity-facing link may have no exported finite native E. Neither
orientation nor generator ownership of a Voronoi cell is inferred.
"""


def audit_cycle_dual_incidence(stars,cycle_sites,face_pairs,incidence,endpoint_ids):
	if len(stars)!=len(cycle_sites):
		raise ValueError("Mismatched cycle and point-star groups")
	by_faces={}
	for eid,pair in face_pairs.items():
		key=frozenset((pair["face_id"],pair["neighbor_face_id"]))
		by_faces.setdefault(key,[]).append(eid)
	results=[]
	for star,cycle in zip(stars,cycle_sites):
		links=cycle.get("adjacent_face_sites",[])
		star_edges={row["edge_id"] for row in star.get("incident_edges",[])}
		valid=(star.get("status")=="native_incident_star_unordered_only"
			and cycle.get("status")=="native_cycle_shared_sites_verified_only"
			and star.get("ownership_proven") is False
			and cycle.get("ownership_proven") is False
			and len(star_edges)==3 and len(links)==4)
		mapped=[]
		if valid:
			for link in links:
				ids=link.get("face_ids",[])
				site=link.get("shared_other_site")
				if len(ids)!=2 or ids[0]==ids[1] or not isinstance(site,list):
					valid=False
					break
				matches=by_faces.get(frozenset(ids),[])
				if site==["INF"]:
					# Unrepresented infinity-facing adjacency must never
					# be silently conflated with an exported finite E.
					if matches:
						valid=False
						break
					mapped.append({"face_ids":ids,"edge_id":None,
						"dual_kind":"unexported_infinite_link"})
					continue
				if len(matches)!=1 or matches[0] not in star_edges:
					valid=False
					break
				eid=matches[0]
				row=incidence.get(eid)
				if row is None or (ids!=[face_pairs[eid]["face_id"],
						face_pairs[eid]["neighbor_face_id"]] and
						ids!=[face_pairs[eid]["neighbor_face_id"],
							face_pairs[eid]["face_id"]]):
					valid=False
					break
				mapped.append({"face_ids":ids,"edge_id":eid,
					"dual_kind":"degenerate_endpoint" if eid in endpoint_ids
						else "non_endpoint",
					"cycle_forward_matches_export":ids[0]==face_pairs[eid]["face_id"],
					"local_index":row["local_index"],
					"neighbor_index":row["neighbor_index"]})
			valid=(valid and {x["edge_id"] for x in mapped if x["edge_id"] is not None}
				==star_edges and sum(x["edge_id"] is None for x in mapped)==1)
		results.append({"edge_ids":star.get("edge_ids",[]),
			"status":"native_cycle_dual_incidence_only" if valid
				else "blocked_cycle_dual_incidence",
			"cycle_links":mapped if valid else [],
			"voronoi_side_proven":False,"ownership_proven":False})
	return results
