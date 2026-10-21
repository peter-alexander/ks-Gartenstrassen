"""Inventory all original native E edges incident to unresolved endpoint vertices.

Vertex-star membership is graph adjacency, not cyclic order or Voronoi ownership.
"""


def audit_endpoint_native_vertex_stars(crosschecks,vertices,edge_ids):
	shared=sorted({row["shared_native_vertex_id"] for row in crosschecks})
	result=[]
	for vid in shared:
		if vid not in vertices or vertices[vid][0]!="P":
			raise ValueError("Endpoint vertex must be an original point site")
		incident=[]
		for eid,(a,b) in sorted(edge_ids.items()):
			if vid not in (a,b):
				continue
			other=b if a==vid else a
			if other not in vertices:
				raise ValueError("Missing neighbor generator vertex")
			site=vertices[other]
			incident.append({"edge_id":eid,"neighbor_vertex_id":other,
				"neighbor_site":{"kind":site[0],"coordinates":list(site[1])}})
		related=[row for row in crosschecks if row["shared_native_vertex_id"]==vid]
		expected={item["edge_id"] for row in related
			for item in row["source_vertex_evidence"]}
		if not expected or not expected.issubset({x["edge_id"] for x in incident}):
			raise ValueError("Missing unresolved ray in original vertex star")
		result.append({"point_vertex_id":vid,
			"point_site":{"kind":vertices[vid][0],"coordinates":list(vertices[vid][1])},
			"incident_native_edges":incident,"unresolved_ray_edge_ids":sorted(expected),
			"status":"native_vertex_star_unordered_no_owner",
			"cyclic_order_proven":False,"ownership_proven":False})
	return result
