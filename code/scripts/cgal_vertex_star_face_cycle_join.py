"""Cross-check complete native point-generator stars against primal face cycles.

A Delaunay face cycle establishes native incidence; it does not assign
Voronoi polygon ownership or determine geometric side labels.
"""


def audit_vertex_star_face_cycles(stars,cycles,face_pairs):
	by_edges={frozenset(row["edge_ids"]):row for row in cycles}
	results=[]
	for star in stars:
		expected=frozenset(star["unresolved_ray_edge_ids"])
		cycle=by_edges.get(expected)
		edge_ids=[row["edge_id"] for row in star["incident_native_edges"]]
		valid=(star.get("status")=="native_vertex_star_unordered_no_owner"
			and star.get("ownership_proven") is False
			and len(edge_ids)==3 and len(set(edge_ids))==3
			and cycle is not None
			and cycle.get("status")=="complete_native_face_cycle_only"
			and cycle.get("cyclic_order_proven") is True
			and cycle.get("ownership_proven") is False)
		faces=list(cycle["face_cycle"]) if valid else []
		observations=[]
		if valid:
			for eid in edge_ids:
				pair=face_pairs.get(eid)
				if pair is None:
					valid=False
					break
				neighbors={pair["face_id"],pair["neighbor_face_id"]}
				observations.append({"edge_id":eid,"adjacent_face_ids":sorted(neighbors),
					"both_in_cycle":neighbors.issubset(faces)})
				if not neighbors.issubset(faces):
					valid=False
			valid=valid and len(set(faces))==len(faces)
		ordered=[]
		if valid:
			# The third E is identified by native face incidence, without
			# treating cyclic primal adjacency as geometric Voronoi ownership.
			rays=set(star["unresolved_ray_edge_ids"])
			others=set(edge_ids)-rays
			pair_by_edge={x["edge_id"]:set(x["adjacent_face_ids"])
				for x in observations}
			valid=(len(others)==1 and all(
				len(pair_by_edge[next(iter(others))]&pair_by_edge[eid])==1
				for eid in rays))
			if valid:
				ordered=sorted(edge_ids,key=lambda eid:(
					min(faces.index(face) for face in pair_by_edge[eid]),eid))
		results.append({"point_vertex_id":star["point_vertex_id"],
			"incident_edge_ids_in_cycle_order":ordered if valid else [],
			"third_edge_id":next(iter(others)) if valid else None,
			"geometric_ray_order_proven":False,
			"incident_edge_face_pairs":observations if valid else [],
			"face_cycle":faces if valid else [],
			"status":"complete_native_vertex_star_face_cycle_only" if valid
				else "blocked_vertex_star_face_cycle_mismatch",
			"cyclic_order_proven":bool(valid),"ownership_proven":False})
	return results
