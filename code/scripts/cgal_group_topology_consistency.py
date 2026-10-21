"""Read-only comparison of native endpoint groups with local cell and neighbor evidence.

A matching group is an internal consistency check, NOT a proof that the
two constituent native bisectors can be replaced by a single ownership
edge. Original labels and polygons remain untouched.
"""


def _site(site):
	if not isinstance(site,dict) or site.get("kind") not in ("P","S"):
		return None
	coords=site.get("coordinates")
	if not isinstance(coords,list):
		return None
	if len(coords)!=(2 if site["kind"]=="P" else 4):
		return None
	return site["kind"],tuple(coords)


def audit_group_topological_consistency(groups,local_sides,neighbor_rows):
	"""Correlate E IDs, local left/right candidates and fixed neighbors.

	A report is blocked unless one-to-one matching and every known
	neighbor constraint are satisfied. Even then: no ownership proof.
	"""
	seen=set()
	by_edges={}
	for row in local_sides:
		key=frozenset(row.get("native_edges",())[i]["edge_id"]
			for i in range(len(row.get("native_edges",()))))
		if len(key)!=2 or key in by_edges:
			raise ValueError("Ambiguous local endpoint side records")
		by_edges[key]=row
	neighbors={row["face_index"]:row for row in neighbor_rows}
	report=[]
	for group in groups:
		key=frozenset(group.get("edge_ids",[]))
		if len(key)!=2 or key in seen:
			raise ValueError("Duplicate or incomplete native endpoint group")
		seen.add(key)
		local=by_edges.get(key)
		left=_site(group.get("left_segment"))
		right=_site(group.get("right_segment"))
		if group.get("status")!="grouped_diagnostic_only" or local is None:
			status="blocked_missing_or_rejected_native_group"
			sides_match=False
			known=0
			conflicts=None
		else:
			sides_match=left==_site(local["candidate_left"]) and (
				right==_site(local["candidate_right"]))
			left_face=local["left_face"]
			right_face=local["right_face"]
			pair=[neighbors.get(left_face),neighbors.get(right_face)]
			known=sum(r["known_neighbor_constraints"] for r in pair if r)
			conflicts=sum(r["known_neighbor_mismatches"] for r in pair if r)
			if left_face==right_face:
				status="blocked_non_distinct_faces"
			elif any(r is None for r in pair):
				status="blocked_missing_neighbor_audit"
			elif known==0:
				status="blocked_no_known_neighbor_constraints"
			elif not sides_match:
				status="blocked_group_side_candidate_mismatch"
			elif conflicts:
				status="blocked_proven_neighbor_conflict"
			elif any(r["unknown_neighbor_constraints"] for r in pair):
				status="blocked_unknown_neighbor"
			else:
				status="consistent_but_ownership_unproven"
		report.append({"edge_ids":sorted(key),
			"local_sides_match_group_segments":sides_match,
			"known_neighbor_constraints":known,
			"known_neighbor_mismatches":conflicts,
			"status":status,
			"ownership_proven":False})
	return report
