"""Strict read-only validation of observed native Delaunay face-chain topology.

A pairwise face chain is not a cyclic rotation or Voronoi ownership proof.
"""


def audit_endpoint_face_chain(adjacency_rows):
	reports=[]
	seen=set()
	for row in adjacency_rows:
		ids=row.get("edge_ids",[])
		third=row.get("third_edge_id")
		key=frozenset([*ids,third])
		if len(key)!=3 or len(ids)!=2 or len(set(ids))!=2 or seen.intersection(key):
			raise ValueError("Invalid or overlapping native face-chain groups")
		seen.update(key)
		pairs=row.get("pairwise_face_connections",[])
		valid=(row.get("status")=="native_three_edge_adjacency_observed_only"
			and row.get("ownership_proven") is False
			and row.get("cyclic_order_proven") is False
			and isinstance(pairs,list) and len(pairs)==3)
		by_pair={}
		if valid:
			for pair in pairs:
				edges=pair.get("edge_ids",[])
				faces=pair.get("shared_face_ids")
				if (len(edges)!=2 or len(set(edges))!=2
					or not set(edges).issubset(key) or not isinstance(faces,list)
					or len(faces)!=len(set(faces))
					or any(type(face) is not int or face<0 for face in faces)):
					valid=False
					break
				pkey=frozenset(edges)
				if pkey in by_pair:
					valid=False
					break
				by_pair[pkey]=faces
		a,b=ids
		if valid:
			ab=by_pair.get(frozenset((a,b)))
			ac=by_pair.get(frozenset((a,third)))
			bc=by_pair.get(frozenset((b,third)))
			valid=(ab==[] and ac is not None and bc is not None
				and len(ac)==1 and len(bc)==1 and ac[0]!=bc[0])
		reports.append({"edge_ids":list(ids),"third_edge_id":third,
			"status":"native_face_chain_confirmed_not_ownership" if valid
				else "blocked_non_chain_or_incomplete_face_topology",
			"shared_with_third":(
				[{"edge_id":a,"face_id":ac[0]},
					{"edge_id":b,"face_id":bc[0]}] if valid else []),
			"cyclic_order_proven":False,"ownership_proven":False})
	return reports
