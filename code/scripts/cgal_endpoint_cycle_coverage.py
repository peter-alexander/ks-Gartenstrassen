"""Validate complete native point-site circulation fixture coverage without ownership promotion."""


def audit_endpoint_cycle_coverage(stars,cycles):
	if len(stars)!=len(cycles) or len(stars)!=2:
		raise ValueError("Expected two native endpoint stars and cycles")
	out=[]
	for star,cycle in zip(stars,cycles):
		ids=star.get("edge_ids",[])
		path=cycle.get("face_cycle",[])
		valid=(star.get("status")=="native_incident_star_unordered_only"
			and star.get("ownership_proven") is False
			and cycle.get("status")=="complete_native_face_cycle_only"
			and cycle.get("cyclic_order_proven") is True
			and cycle.get("ownership_proven") is False
			and len(ids)==2 and len(set(ids))==2
			and set(ids)==set(cycle.get("edge_ids",[]))
			and len(star.get("incident_edges",[]))==3
			and len({edge.get("edge_id") for edge in star["incident_edges"]})==3
			and len(path)==4 and len(set(path))==4
			and all(type(fid) is int and fid>=0 for fid in path))
		out.append({"edge_ids":list(ids),
			"status":"native_four_face_cycle_observed_no_ownership" if valid
				else "blocked_incomplete_native_cycle_coverage",
			"face_cycle":list(path) if valid else [],
			"cyclic_order_proven":bool(valid),"ownership_proven":False})
	return out
