"""Read-only comparison of native endpoint groups with local cell and neighbor evidence.

Regular-edge neighbor agreement is distinct from endpoint-dual evidence.
A coincident native endpoint group is never an ownership proof; original
labels and polygons remain untouched.
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


def _checked_neighbor(row):
	"""Reject inconsistent audit summaries rather than trusting only totals."""
	checks=row.get("known_checks")
	unknown=row.get("unknown_checks")
	endpoint=row.get("endpoint_checks")
	if not all(isinstance(items,list) for items in (checks,unknown,endpoint)):
		return False
	if any(not isinstance(check,dict) for check in checks+unknown+endpoint):
		return False
	return (len(checks)==row.get("known_neighbor_constraints")
		and len(unknown)==row.get("unknown_neighbor_constraints")
		and len(endpoint)==row.get("endpoint_edge_fragments")
		and sum(check.get("exact_pair") is not True for check in checks)
			==row.get("known_neighbor_mismatches")
		and sum(check.get("contains_candidate") is not True for check in endpoint)
			==row.get("endpoint_candidate_conflicts"))


def audit_group_topological_consistency(groups,local_sides,neighbor_rows):
	"""Compare two grouped native E IDs with local sides and fixed neighbors.

	Endpoint dual pair disagreements are reported explicitly and must NOT
	be counted as ordinary-edge proof conflicts or as ownership evidence.
	"""
	by_edges={}
	for row in local_sides:
		native=row.get("native_edges",[])
		key=frozenset(edge.get("edge_id") for edge in native)
		if len(key)!=2 or len(native)!=2 or key in by_edges:
			raise ValueError("Ambiguous local endpoint side records")
		by_edges[key]=row
	neighbors={}
	for row in neighbor_rows:
		face=row["face_index"]
		if face in neighbors:
			raise ValueError("Duplicate endpoint neighbor face")
		neighbors[face]=row
	report=[]
	seen=set()
	used_edges=set()
	for group in groups:
		edge_ids=group.get("edge_ids",[])
		key=frozenset(edge_ids)
		if len(key)!=2 or len(edge_ids)!=2 or key in seen or used_edges.intersection(key):
			raise ValueError("Duplicate, overlapping or incomplete native endpoint group")
		seen.add(key)
		used_edges.update(key)
		local=by_edges.get(key)
		left=_site(group.get("left_segment"))
		right=_site(group.get("right_segment"))
		known=0
		conflicts=None
		endpoint_fragments=0
		endpoint_conflicts=0
		sides_match=False
		if (group.get("status")!="grouped_diagnostic_only" or local is None):
			status="blocked_missing_or_rejected_native_group"
		elif group.get("ownership_proven") is not False or local.get("ownership_proven") is not False:
			status="blocked_unexpected_proof_claim"
		else:
			sides_match=(left is not None and right is not None
				and left==_site(local.get("candidate_left"))
				and right==_site(local.get("candidate_right")))
			left_face=local.get("left_face")
			right_face=local.get("right_face")
			if left_face==right_face or not all(isinstance(f,int) for f in (left_face,right_face)):
				status="blocked_invalid_local_face_pair"
			else:
				pair=[neighbors.get(left_face),neighbors.get(right_face)]
				known=sum(r.get("known_neighbor_constraints",0) for r in pair if r)
				conflicts=sum(r.get("known_neighbor_mismatches",0) for r in pair if r)
				endpoint_fragments=sum(r.get("endpoint_edge_fragments",0) for r in pair if r)
				endpoint_conflicts=sum(r.get("endpoint_candidate_conflicts",0) for r in pair if r)
				if any(r is None for r in pair):
					status="blocked_missing_neighbor_audit"
				elif not sides_match:
					status="blocked_group_side_candidate_mismatch"
				elif (_site(pair[0].get("candidate_site"))!=left
						or _site(pair[1].get("candidate_site"))!=right):
					status="blocked_neighbor_candidate_mismatch"
				elif any(not _checked_neighbor(r) for r in pair):
					status="blocked_inconsistent_neighbor_evidence"
				elif conflicts:
					status="blocked_proven_neighbor_conflict"
				elif any(r["unknown_neighbor_constraints"] for r in pair):
					status="blocked_unknown_neighbor"
				elif any(r["known_neighbor_constraints"]==0 for r in pair):
					status="blocked_insufficient_regular_neighbor_evidence"
				elif any(r["endpoint_edge_fragments"]==0 for r in pair):
					status="blocked_missing_endpoint_evidence"
				else:
					status="regular_neighbors_consistent_endpoint_ambiguous"
		report.append({"edge_ids":sorted(key),
			"local_sides_match_group_segments":sides_match,
			"known_neighbor_constraints":known,
			"known_neighbor_mismatches":conflicts,
			"endpoint_edge_fragments":endpoint_fragments,
			"endpoint_candidate_conflicts":endpoint_conflicts,
			"status":status,
			"ownership_proven":False})
	return report
