"""Fail-closed verification of coincident endpoint rays and zero-length third duals.

The native topology remains nonempty even when the third dual collapses.
No Voronoi polygon-side or generator ownership follows from this geometry.
"""


def audit_endpoint_zero_length_third_dual(stars,primitives):
	if len(stars)!=len(primitives):
		raise ValueError("Inconsistent native endpoint group counts")
	result=[]
	for star,group in zip(stars,primitives):
		base=set(star.get("edge_ids",[]))
		records=group.get("edge_primitives",[])
		by_id={record["edge_id"]:record["primitives"] for record in records}
		valid=(star.get("status")=="native_incident_star_unordered_only"
			and group.get("status")=="native_endpoint_dual_primitives_recorded_only"
			and star.get("ownership_proven") is False
			and group.get("ownership_proven") is False
			and group.get("voronoi_side_proven") is False
			and len(base)==2 and len(by_id)==3 and base.issubset(by_id))
		third=None
		if valid:
			third=next(iter(set(by_id)-base))
			pair=[by_id[eid] for eid in sorted(base)]
			single=by_id[third]
			valid=(all(len(items)==1 and items[0].get("kind")=="R"
				for items in pair) and len(single)==1
				and single[0].get("kind")=="S"
				and pair[0][0]["coordinates"]==pair[1][0]["coordinates"])
			if valid:
				a=single[0]["coordinates"]
				b=pair[0][0]["coordinates"]
				valid=(len(a)==4 and len(b)==4
					and a[0]==a[2] and a[1]==a[3]
					and a[:2]==b[:2] and b[:2]!=b[2:])
		result.append({"edge_ids":star.get("edge_ids",[]),
			"status":"native_coincident_rays_zero_third_dual_only" if valid
				else "blocked_endpoint_dual_geometry_pattern",
			"third_edge_id":third if valid else None,
			"voronoi_side_proven":False,"ownership_proven":False})
	return result
