"""Verify native endpoint face-chain links against the mirrored primal slots.

Checks existing CGAL evidence only. This is not a vertex circulator or
a proof of cyclic order or Voronoi generator ownership.
"""


def audit_endpoint_mirror_chain(chains,face_pairs,incidence,neighbors):
	faces=neighbors.get("faces",{})
	results=[]
	for chain in chains:
		ids=chain.get("edge_ids",[])
		third=chain.get("third_edge_id")
		links=chain.get("shared_with_third",[])
		valid=(chain.get("status")=="native_face_chain_confirmed_not_ownership"
			and chain.get("cyclic_order_proven") is False
			and chain.get("ownership_proven") is False
			and len(ids)==2 and len(set(ids))==2
			and third not in ids and len(links)==2
			and {link.get("edge_id") for link in links}==set(ids))
		evidence=[]
		if valid:
			for link in links:
				eid=link["edge_id"]
				common=link.get("face_id")
				pair=face_pairs.get(eid)
				bridge=face_pairs.get(third)
				a=incidence.get(eid)
				b=incidence.get(third)
				if any(x is None for x in (pair,bridge,a,b)):
					valid=False
					break
				x,y=pair["face_id"],pair["neighbor_face_id"]
				u,v=bridge["face_id"],bridge["neighbor_face_id"]
				if common not in (x,y) or common not in (u,v):
					valid=False
					break
				i,j=a["local_index"],a["neighbor_index"]
				k,l=b["local_index"],b["neighbor_index"]
				if (any(type(slot) is not int or slot not in range(3)
						for slot in (i,j,k,l))
					or any(fid not in faces or len(faces[fid])!=3
						for fid in (x,y,u,v))
					or faces[x][i]!=y or faces[y][j]!=x
					or faces[u][k]!=v or faces[v][l]!=u):
					valid=False
					break
				evidence.append({"edge_id":eid,"third_edge_id":third,
					"shared_face_id":common})
		results.append({"edge_ids":list(ids),"third_edge_id":third,
			"status":"mirror_chain_consistent_no_rotation_proof" if valid
				else "blocked_mirror_chain_evidence",
			"verified_links":evidence if valid else [],
			"cyclic_order_proven":False,"ownership_proven":False})
	return results
