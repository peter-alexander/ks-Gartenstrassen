"""Cross-check observed polygon sides with isolated coincident-ray E conflicts.

Polygon geometry establishes left/right sampling only. Matching an E site's
pair to a candidate is NOT proof that the candidate owns the polygon.
"""


def audit_unresolved_side_conflict_crosscheck(sides,conflicts,*,tolerance=1e-8):
	if tolerance<=0:
		raise ValueError("Invalid tolerance")
	by_face={}
	for row in conflicts:
		fid=row["face_index"]
		if fid in by_face:
			raise ValueError("Duplicate unresolved face")
		by_face[fid]=row
	report=[]
	covered=set()
	for side in sides:
		a,b=side.get("left_face"),side.get("right_face")
		if a==b or a not in by_face or b not in by_face:
			continue
		covered.update((a,b))
		edge_ids={r["edge_id"] for r in side.get("native_edges",[])}
		valid=(side.get("ownership_proven") is False
			and len(edge_ids)==2 and len(side.get("native_edges",[]))==2
			and side.get("shared_forward_m",0)>tolerance)
		per_face=[]
		for fid,which,candidate in (
				(a,"left",side.get("candidate_left")),
				(b,"right",side.get("candidate_right"))):
			item=by_face[fid]
			matches=item.get("matching_endpoint_sources",[])
			opposites=item.get("conflicting_endpoint_sources",[])
			matched={x["edge_id"] for x in matches}
			opposed={x["edge_id"] for x in opposites}
			ok=(item.get("status")=="coincident_endpoint_conflict_isolated_not_resolved"
				and item.get("ownership_proven") is False
				and candidate==item.get("candidate_site")
				and len(matched)==len(opposed)==1 and matched.isdisjoint(opposed)
				and matched|opposed==edge_ids
				and all(abs(x.get("intersection_length_m",0)-side["shared_forward_m"])<=tolerance
					for x in matches+opposites)
				and all(
					edge.get("candidate_on_left" if which=="left" else "candidate_on_right") is
						(edge["edge_id"] in matched)
					for edge in side["native_edges"]))
			valid=valid and ok
			per_face.append({"face_index":fid,"geometric_side":which,
				"matching_edge_ids":sorted(matched),"conflicting_edge_ids":sorted(opposed)})
		report.append({"face_indices":[a,b],
			"status":"geometric_sides_and_conflicts_consistent_only" if valid
				else "blocked_geometric_side_conflict_mismatch",
			"face_evidence":per_face if valid else [],
			"ownership_proven":False})
	if covered!=set(by_face):
		raise ValueError("Not every unresolved conflict has geometric side evidence")
	return report
