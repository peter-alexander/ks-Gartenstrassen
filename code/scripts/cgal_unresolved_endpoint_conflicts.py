"""Trace unresolved-face candidate conflicts to proven coincident endpoint rays.

An overlapping conflicting native source is not discarded or treated as
a proof of polygon ownership.
"""


def audit_unresolved_endpoint_conflicts(candidates,census,stars,zero_duals):
	if len(stars)!=len(zero_duals):
		raise ValueError("Mismatched native endpoint groups")
	groups=[]
	for star,zero in zip(stars,zero_duals):
		ids=star.get("edge_ids",[])
		if (star.get("status")!="native_incident_star_unordered_only"
			or zero.get("status")!="native_coincident_rays_zero_third_dual_only"
			or star.get("ownership_proven") is not False
			or zero.get("ownership_proven") is not False
			or len(ids)!=2 or len(set(ids))!=2):
			raise ValueError("Unverified coincident-ray group")
		groups.append(frozenset(ids))
	by_face={row["face_index"]:row for row in census}
	report=[]
	for candidate in candidates:
		if candidate.get("status")!="candidate_only_not_proven":
			continue
		fid=candidate["face_index"]
		row=by_face.get(fid)
		site=candidate.get("candidate_site")
		if row is None or not isinstance(site,dict) or row.get("ownership_proven") is not False:
			raise ValueError("Missing unresolved native source evidence")
		key=(site.get("kind"),tuple(site.get("coordinates",[])))
		matches=[]
		conflicts=[]
		for source in row["boundary_source_records"]:
			pair=frozenset((s["kind"],tuple(s["coordinates"])) for s in source["sites"])
			if source["primitive_kind"]!="R" or not any(source["edge_id"] in group for group in groups):
				continue
			item={"edge_id":source["edge_id"],
				"intersection_length_m":source["intersection_length_m"]}
			(matches if key in pair else conflicts).append(item)
		touched=[group for group in groups if any(
			x["edge_id"] in group for x in matches+conflicts)]
		valid=(len(touched)==1 and len(matches)==1 and len(conflicts)==1
			and {x["edge_id"] for x in matches+conflicts}==touched[0]
			and candidate.get("endpoint_conflicting_pairs")==1
			and candidate.get("ownership_proven",False) is False)
		report.append({"face_index":fid,"candidate_site":site,
			"status":"coincident_endpoint_conflict_isolated_not_resolved" if valid
				else "blocked_or_unclassified_endpoint_conflict",
			"matching_endpoint_sources":matches,
			"conflicting_endpoint_sources":conflicts,
			"ownership_proven":False})
	return report
