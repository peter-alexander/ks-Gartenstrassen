"""Read-only alignment of native CW/CCW with point-star cycle traversal.

The relative orientation of native Face handles does not independently
prove which Voronoi polygon is on either side of a degenerate dual.
"""


def audit_endpoint_cw_ccw_cycle_alignment(dual_groups,cw_groups):
	if len(dual_groups)!=len(cw_groups):
		raise ValueError("Mismatched native endpoint groups")
	report=[]
	for dual,cw in zip(dual_groups,cw_groups):
		links=dual.get("cycle_links",[])
		pairs=cw.get("native_pairs",[])
		by_edge={row.get("edge_id"):row for row in pairs}
		valid=(dual.get("status")=="native_cycle_dual_incidence_only"
			and cw.get("status")=="native_endpoint_cw_ccw_pair_recorded_only"
			and dual.get("ownership_proven") is False
			and cw.get("ownership_proven") is False
			and dual.get("voronoi_side_proven") is False
			and cw.get("voronoi_side_proven") is False
			and len(links)==4 and len(pairs)==3 and len(by_edge)==3
			and set(dual.get("edge_ids",[]))==set(cw.get("edge_ids",[])))
		rows=[]
		if valid:
			for link in links:
				eid=link.get("edge_id")
				if eid is None:
					if link.get("dual_kind")!="unexported_infinite_link":
						valid=False
					continue
				pair=by_edge.get(eid)
				if (pair is None or link.get("dual_kind")!="degenerate_endpoint"
					or type(link.get("cycle_forward_matches_export")) is not bool):
					valid=False
					break
				cw_site=pair.get("cw_site")
				ccw_site=pair.get("ccw_site")
				if (not isinstance(cw_site,list) or not isinstance(ccw_site,list)
					or len(cw_site) not in (3,5) or len(ccw_site) not in (3,5)
					or cw_site==ccw_site):
					valid=False
					break
				rows.append({"edge_id":eid,
					"cycle_forward_matches_export":link["cycle_forward_matches_export"],
					"cw_site":cw_site,"ccw_site":ccw_site})
			valid=valid and len(rows)==3 and {r["edge_id"] for r in rows}==set(by_edge)
		report.append({"edge_ids":dual.get("edge_ids",[]),
			"status":"native_cw_ccw_cycle_alignment_only" if valid
				else "blocked_cw_ccw_cycle_alignment",
			"ordered_links":rows if valid else [],
			"voronoi_side_proven":False,"ownership_proven":False})
	return report
