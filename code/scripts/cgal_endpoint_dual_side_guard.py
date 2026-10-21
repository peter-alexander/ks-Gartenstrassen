"""Fail-closed guard: oriented native endpoint duals are not regular side proofs."""


def audit_endpoint_dual_side_evidence(dual_groups,regular_sides):
	regular_ids={row["edge_id"] for row in regular_sides
		if row.get("locally_verified") is True}
	report=[]
	for group in dual_groups:
		links=group.get("cycle_links",[])
		finite=[link for link in links if link.get("edge_id") is not None]
		valid=(group.get("status")=="native_cycle_dual_incidence_only"
			and group.get("ownership_proven") is False
			and group.get("voronoi_side_proven") is False
			and len(links)==4 and len(finite)==3
			and len({link["edge_id"] for link in finite})==3
			and all(link.get("dual_kind")=="degenerate_endpoint" for link in finite)
			and all(link["edge_id"] not in regular_ids for link in finite)
			and len(links)-len(finite)==1
			and any(link.get("dual_kind")=="unexported_infinite_link"
				and link.get("edge_id") is None for link in links))
		report.append({"edge_ids":group.get("edge_ids",[]),
			"status":"degenerate_duals_require_independent_side_proof" if valid
				else "blocked_mixed_or_missing_side_evidence",
			"degenerate_edge_ids":sorted(link["edge_id"] for link in finite)
				if valid else [],
			"voronoi_side_proven":False,"ownership_proven":False})
	return report
