"""Read-only face-handle adjacency among all three native point-site edges.

A connected face graph is not a cyclic rotation or ownership proof.
"""


def audit_three_edge_face_adjacency(third_edges,face_pairs):
	reports=[]
	for row in third_edges:
		ids=row.get("edge_ids",[])
		third=row.get("third_edge_id")
		valid=(row.get("status")=="third_native_edge_observed_no_rotation_proof"
			and row.get("ownership_proven") is False
			and row.get("cyclic_order_proven") is False
			and len(ids)==2 and len(set(ids))==2 and third not in ids
			and third is not None
			and all(edge_id in face_pairs for edge_id in (*ids,third)))
		pairs=[]
		if valid:
			for a,b in ((ids[0],ids[1]),(ids[0],third),(ids[1],third)):
				first=face_pairs[a]
				second=face_pairs[b]
				common=sorted(set(first.values()).intersection(second.values()))
				pairs.append({"edge_ids":[a,b],"shared_face_ids":common})
		reports.append({"edge_ids":list(ids),
			"third_edge_id":third,
			"status":"native_three_edge_adjacency_observed_only" if valid
				else "blocked_incomplete_three_edge_face_evidence",
			"pairwise_face_connections":pairs if valid else [],
			"cyclic_order_proven":False,"ownership_proven":False})
	return reports
