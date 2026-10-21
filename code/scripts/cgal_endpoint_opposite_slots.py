"""Verify point-site membership is not the opposite vertex of its primal edge.

Uses original CGAL face indices and point-site vertex slots from one run.
Does not establish cyclic order or Voronoi ownership.
"""


def audit_endpoint_primal_opposite_slots(stars,vertex_slots,face_pairs,incidence):
	if len(stars)!=len(vertex_slots):
		raise ValueError("Mismatched native point-star and vertex-slot groups")
	result=[]
	for star,vertices in zip(stars,vertex_slots):
		edges=star.get("incident_edges",[])
		point_slots={r["face_id"]:r["vertex_slot"]
			for r in vertices.get("face_vertex_slots",[])}
		valid=(star.get("status")=="native_incident_star_unordered_only"
			and vertices.get("status")=="native_point_vertex_slots_observed_only"
			and star.get("ownership_proven") is False
			and vertices.get("ownership_proven") is False
			and star.get("cyclic_order_proven") is False
			and vertices.get("cyclic_order_proven") is False
			and set(star.get("edge_ids",[]))==set(vertices.get("edge_ids",[]))
			and len(edges)==3 and len(point_slots)==len(vertices.get("face_vertex_slots",[])))
		checked=[]
		if valid:
			for edge in edges:
				eid=edge.get("edge_id")
				pair=face_pairs.get(eid)
				row=incidence.get(eid)
				if pair is None or row is None:
					valid=False
					break
				for face_id,index in ((pair["face_id"],row["local_index"]),
						(pair["neighbor_face_id"],row["neighbor_index"])):
					point_index=point_slots.get(face_id)
					if (type(index) is not int or type(point_index) is not int
							or index not in range(3) or point_index not in range(3)
							or point_index==index):
						valid=False
						break
					checked.append({"edge_id":eid,"face_id":face_id,
						"point_vertex_slot":point_index,"opposite_vertex_slot":index})
				if not valid:
					break
		result.append({"edge_ids":list(star.get("edge_ids",[])),
			"status":"native_point_on_primal_edge_checked_only" if valid
				else "blocked_point_opposite_slot_conflict",
			"checked_incidence":checked if valid else [],
			"cyclic_order_proven":False,"ownership_proven":False})
	return result
