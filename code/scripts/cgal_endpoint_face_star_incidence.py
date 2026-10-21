"""Cross-check native point-site star edges against shared Delaunay face IDs.

Read-only. Shared face handles confirm primal adjacency, not cyclic rotation
or Voronoi-cell generator ownership.
"""


def audit_endpoint_face_star_incidence(stars,chains,face_pairs):
	if len(stars)!=len(chains):
		raise ValueError("Different native star/chain counts")
	reports=[]
	for star,chain in zip(stars,chains):
		ids=chain.get("edge_ids",[])
		third=chain.get("third_edge_id")
		incident=star.get("incident_edges",[])
		by_edge={row["edge_id"]:row for row in incident}
		links=chain.get("shared_with_third",[])
		valid=(star.get("status")=="native_incident_star_unordered_only"
			and chain.get("status")=="native_face_chain_confirmed_not_ownership"
			and star.get("ownership_proven") is False
			and chain.get("ownership_proven") is False
			and star.get("cyclic_order_proven") is False
			and chain.get("cyclic_order_proven") is False
			and len(ids)==2 and len(set(ids))==2
			and set(star.get("edge_ids",[]))==set(ids)
			and len(incident)==3 and len(by_edge)==3
			and set(by_edge)==set([*ids,third])
			and len(links)==2
			and {link.get("edge_id") for link in links}==set(ids))
		if valid:
			for link in links:
				edge_id,face_id=link.get("edge_id"),link.get("face_id")
				first,bridge=face_pairs.get(edge_id),face_pairs.get(third)
				if (first is None or bridge is None or type(face_id) is not int
					or set(first.values()).intersection(bridge.values())!={face_id}):
					valid=False
					break
		reports.append({"edge_ids":list(ids),"third_edge_id":third,
			"status":"native_face_star_incidence_checked_only" if valid
				else "blocked_face_star_incidence_mismatch",
			"verified_shared_face_links":links if valid else [],
			"cyclic_order_proven":False,"ownership_proven":False})
	return reports
