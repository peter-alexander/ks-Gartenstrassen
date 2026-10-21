"""Read-only native Delaunay incidence signatures for coincident endpoint groups.

Indices are local to their respective triangular faces. Equal/different
index values are observations only, never ownership orientation rules.
"""


def audit_group_primal_indices(groups,incidence):
	"""Preserve each constituent E record without collapsing native evidence."""
	seen=set()
	report=[]
	for group in groups:
		edge_ids=group.get("edge_ids",[])
		if len(edge_ids)!=2 or len(set(edge_ids))!=2 or seen.intersection(edge_ids):
			raise ValueError("Duplicate, overlapping or incomplete endpoint group")
		seen.update(edge_ids)
		rows=[]
		for edge_id in edge_ids:
			row=incidence.get(edge_id)
			if row is None or any(type(row.get(key)) is not int or row[key] not in (0,1,2)
					for key in ("local_index","neighbor_index")) or (
					any(type(row.get(key)) is not bool for key in ("primary_finite","neighbor_finite"))
					or row["primary_finite"]==row["neighbor_finite"]
					or not isinstance(row.get("opposite_sites"),str)):
				rows=[]
				break
			rows.append({"edge_id":edge_id,"local_index":row["local_index"],
				"neighbor_index":row["neighbor_index"],
				"primary_finite":row["primary_finite"],
				"neighbor_finite":row["neighbor_finite"],
				"opposite_sites":row["opposite_sites"]})
		valid=(group.get("status")=="grouped_diagnostic_only"
			and group.get("ownership_proven") is False and len(rows)==2
			and rows[0]["opposite_sites"]==rows[1]["opposite_sites"])
		report.append({"edge_ids":list(edge_ids),
			"status":"native_incidence_recorded_not_ownership" if valid else "blocked_incomplete_or_inconsistent_incidence",
			"native_records":rows if valid else [],
			"same_local_index":(rows[0]["local_index"]==rows[1]["local_index"]) if valid else None,
			"same_neighbor_index":(rows[0]["neighbor_index"]==rows[1]["neighbor_index"]) if valid else None,
			"ownership_proven":False})
	return report
