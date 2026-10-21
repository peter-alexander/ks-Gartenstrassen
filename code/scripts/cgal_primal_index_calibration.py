"""Compare native endpoint index signatures with independently verified regular rays.

Indices belong to different primal faces; the comparison is descriptive,
not a transfer of left/right ownership across degenerate configurations.
"""


def _signature(row):
	keys=("local_index","neighbor_index")
	if any(type(row.get(key)) is not int or row[key] not in (0,1,2) for key in keys):
		return None
	if any(type(row.get(key)) is not bool for key in ("primary_finite","neighbor_finite")):
		return None
	return tuple(row[key] for key in (*keys,"primary_finite","neighbor_finite"))


def audit_primal_index_calibration(group_indices,regular_rows):
	"""Report exact signature matches and observed regular sides, never inferred sites."""
	calibration={}
	for row in regular_rows:
		if row.get("locally_verified") is not True or type(row.get("left_site_is_first")) is not bool:
			continue
		sig=_signature(row)
		if sig is None:
			continue
		calibration.setdefault(sig,[]).append((row["edge_id"],row["left_site_is_first"]))
	report=[]
	for group in group_indices:
		out={"edge_ids":group.get("edge_ids",[]),"ownership_proven":False,
			"status":"comparison_only_no_ownership_inference","native_edges":[]}
		if group.get("status")!="native_incidence_recorded_not_ownership" or group.get("ownership_proven") is not False:
			out["status"]="blocked_invalid_group_incidence"
		else:
			rows=group.get("native_records",[])
			if len(rows)!=2 or len({row.get("edge_id") for row in rows})!=2 or set(row["edge_id"] for row in rows)!=set(out["edge_ids"]):
				out["status"]="blocked_invalid_group_incidence"
			else:
				for row in rows:
					sig=_signature(row)
					if sig is None:
						out["status"]="blocked_invalid_group_incidence"
						out["native_edges"]=[]
						break
					observations=calibration.get(sig,[])
					out["native_edges"].append({"edge_id":row["edge_id"],
						"signature":list(sig),"regular_matching_edge_ids":[e for e,_ in observations],
						"regular_observed_left_first":sum(side for _,side in observations),
						"regular_observed_right_first":sum(not side for _,side in observations),
						"evidence_status":"no_regular_match" if not observations else
							"conflicting_regular_observations" if len({side for _,side in observations})>1
							else "regular_observation_only"})
		report.append(out)
	return report
