"""Read-only native point-site edge-star inventory for coincident endpoint groups.

An unordered incident-edge inventory is NOT a cyclic Delaunay rotation,
Voronoi ownership proof, or a reconstruction of face adjacency.
"""


def audit_endpoint_primal_star(groups,edges,incidence):
	by_edge={edge_id:pair for edge_id,pair,_ in edges}
	report=[]
	for group in groups:
		point=group.get("point_site")
		ids=group.get("edge_ids",[])
		if (group.get("status")!="grouped_diagnostic_only"
				or group.get("ownership_proven") is not False
				or not isinstance(point,dict) or point.get("kind")!="P"
				or not isinstance(point.get("coordinates"),list)
				or len(point["coordinates"])!=2 or len(ids)!=2 or len(set(ids))!=2):
			report.append({"edge_ids":ids,"status":"blocked_invalid_group",
				"ownership_proven":False})
			continue
		native_point=("P",tuple(point["coordinates"]))
		incident=[]
		for edge_id,pair in by_edge.items():
			if native_point not in pair:
				continue
			row=incidence.get(edge_id)
			if row is None or any(key not in row for key in (
					"local_index","neighbor_index","primary_finite",
					"neighbor_finite","opposite_sites")):
				incident=[]
				break
			incident.append({"edge_id":edge_id,
					"other_sites":[{"kind":s[0],"coordinates":list(s[1])}
						for s in pair if s!=native_point],
					"local_index":row["local_index"],
					"neighbor_index":row["neighbor_index"],
					"primary_finite":row["primary_finite"],
					"neighbor_finite":row["neighbor_finite"],
					"opposite_sites":row["opposite_sites"]})
		valid=(len(incident)>0 and set(ids).issubset(
			{row["edge_id"] for row in incident}))
		report.append({"edge_ids":list(ids),
			"point_site":point,
			"status":"native_incident_star_unordered_only" if valid
				else "blocked_missing_native_star_evidence",
			"incident_edges":sorted(incident,key=lambda row:row["edge_id"]) if valid else [],
			"cyclic_order_proven":False,
			"ownership_proven":False})
	return report
