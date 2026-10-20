"""Audit ordinary-site candidates against proven neighboring native dual pairs.

This intentionally cannot promote an endpoint-dual candidate to a proven
label: a segment-endpoint dual can separate genuine Voronoi cells. The
report specifies exactly which neighbor constraints are satisfied and
which endpoint edges still require an orientation/ownership proof.
"""
from scripts.cgal_endpoint_dual_candidates import is_endpoint_pair
from scripts.cgal_directed_boundary_audit import directed_face_edges


def audit_endpoint_neighbor_constraints(polygons,labels,labelled_segments,
		window,*,tolerance=1e-8):
	if len(polygons)!=len(labels) or tolerance<=0:
		raise ValueError("Invalid endpoint neighbor audit inputs")
	from scripts.cgal_endpoint_dual_candidates import audit_endpoint_dual_candidates
	candidates=audit_endpoint_dual_candidates(polygons,labels,
		labelled_segments,window,tolerance=tolerance)
	targets={r["face_index"]:r for r in candidates
		if r["status"]=="candidate_only_not_proven"}
	if not targets:
		return []
	directed=directed_face_edges(polygons,labels,labelled_segments,
		face_ids=sorted(targets),tolerance=tolerance,limit=100000)
	report=[]
	for record in directed:
		i=record["face_index"]
		raw=targets[i]["candidate_site"]
		candidate=(raw["kind"],tuple(raw["coordinates"]))
		checked=[]
		mismatches=[]
		unresolved=[]
		endpoint_edges=[]
		for edge in record["reported_edges"]:
			pair=frozenset((site["kind"],tuple(site["coordinates"]))
				for site in edge["sites"])
			if is_endpoint_pair(pair):
				endpoint_edges.append({"source_index":edge["source_index"],
					"neighbor_faces":[n["face_index"] for n in edge["neighbor_faces"]],
					"contains_candidate":candidate in pair})
				continue
			for neighbor in edge["neighbor_faces"]:
				j=neighbor["face_index"]
				if labels[j] is None:
					unresolved.append({"source_index":edge["source_index"],
						"neighbor_face":j,"candidate_in_pair":candidate in pair})
					continue
				expected=frozenset((candidate,labels[j]))
				check={"source_index":edge["source_index"],
					"neighbor_face":j,"candidate_in_pair":candidate in pair,
					"neighbor_in_pair":labels[j] in pair,
					"exact_pair":expected==pair}
				checked.append(check)
				if not check["exact_pair"]:
					mismatches.append(check)
		# An ordinary-edge candidate is only eligible for *future*
		# topological proof if all fixed neighbor evidence is consistent.
		# Presence of even one endpoint edge still blocks promotion.
		report.append({"face_index":i,"candidate_site":raw,
			"known_neighbor_constraints":len(checked),
			"known_neighbor_mismatches":len(mismatches),
			"unknown_neighbor_constraints":len(unresolved),
			"endpoint_edge_fragments":len(endpoint_edges),
			"endpoint_candidate_conflicts":sum(
				not e["contains_candidate"] for e in endpoint_edges),
			"known_checks":checked,"unknown_checks":unresolved,
			"endpoint_checks":endpoint_edges,
			"eligible_for_proof":False,
			"blocking_reason":("known_neighbor_conflict" if mismatches
				else "endpoint_side_ownership_not_proven" if endpoint_edges
				else "other_incomplete_topological_evidence")})
	return report
