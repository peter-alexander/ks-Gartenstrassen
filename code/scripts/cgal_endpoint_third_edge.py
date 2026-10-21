"""Conservatively inspect the third native edge of a point-site endpoint group.

Three incident edges do not establish their cyclic order or Voronoi ownership.
"""
def audit_endpoint_third_edges(groups,stars):
	if len(groups)!=len(stars):
		raise ValueError("Mismatched group/star count")
	reports=[]
	for group,star in zip(groups,stars):
		ids=group.get("edge_ids",[])
		edges=star.get("incident_edges",[])
		valid=(group.get("status")=="grouped_diagnostic_only"
			and group.get("ownership_proven") is False
			and star.get("status")=="native_incident_star_unordered_only"
			and star.get("ownership_proven") is False
			and star.get("cyclic_order_proven") is False
			and group.get("point_site")==star.get("point_site")
			and len(ids)==2 and len(set(ids))==2
			and set(ids)==set(star.get("edge_ids",[]))
			and len(edges)==3 and len({e.get("edge_id") for e in edges})==3
			and set(ids).issubset({e.get("edge_id") for e in edges}))
		third=None
		if valid:
			third=next(e for e in edges if e["edge_id"] not in ids)
			valid=(third.get("primary_finite") is True
				and third.get("neighbor_finite") is True
				and all(e.get("primary_finite") is False
					and e.get("neighbor_finite") is True
					for e in edges if e["edge_id"] in ids))
		reports.append({"edge_ids":list(ids),
			"status":"third_native_edge_observed_no_rotation_proof" if valid
				else "blocked_missing_or_unexpected_third_edge",
			"third_edge_id":third["edge_id"] if valid else None,
			"third_edge_other_sites":third["other_sites"] if valid else [],
			"cyclic_order_proven":False,"ownership_proven":False})
	return reports
