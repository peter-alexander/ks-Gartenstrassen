"""Conservative rotation traversal across native CGAL face neighbors around a point.

Only a complete, reciprocal single cycle is accepted. Incomplete face stars
remain blocked. This proves a native face rotation, not Voronoi ownership.
"""


def audit_endpoint_face_circulation(stars,vertex_slots,neighbors):
	faces=neighbors.get("faces",{})
	output=[]
	for star,vertices in zip(stars,vertex_slots):
		slots={r["face_id"]:r["vertex_slot"] for r in vertices.get("face_vertex_slots",[])}
		valid=(star.get("status")=="native_incident_star_unordered_only"
			and vertices.get("status")=="native_point_vertex_slots_observed_only"
			and star.get("ownership_proven") is False
			and vertices.get("ownership_proven") is False
			and len(slots)==len(vertices.get("face_vertex_slots",[]))
			and len(slots)>=3)
		adj={}
		if valid:
			for face_id,v in slots.items():
				row=faces.get(face_id)
				if type(v) is not int or v not in range(3) or row is None or len(row)!=3:
					valid=False
					break
				# Opposite slots other than v represent the two primal edges
				# containing the point vertex. No geometric order assumed.
				next_faces={row[i] for i in range(3) if i!=v}
				if len(next_faces)!=2 or not next_faces.issubset(slots):
					valid=False
					break
				adj[face_id]=next_faces
		if valid:
			valid=all(face_id in adj[n] for face_id,ns in adj.items() for n in ns)
		sequence=[]
		if valid:
			start=min(adj)
			previous=None
			current=start
			for _ in range(len(adj)):
				if current in sequence:
					valid=False
					break
				sequence.append(current)
				candidates=sorted(adj[current]-({previous} if previous is not None else set()))
				if not candidates:
					valid=False
					break
				follow=candidates[0]
				previous,current=current,follow
			valid=valid and current==start and len(sequence)==len(adj)
		output.append({"edge_ids":list(star.get("edge_ids",[])),
			"status":"complete_native_face_cycle_only" if valid
				else "blocked_incomplete_or_ambiguous_face_circulation",
			"face_cycle":sequence if valid else [],
			"cyclic_order_proven":bool(valid),
			"ownership_proven":False})
	return output
