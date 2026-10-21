"""Read-only finite/infinite primal-face orientation hypothesis audit.

A known Voronoi left/right side is an observation, not a proof that the
rule generalizes to degenerate endpoint duals. Reject unknown geometry.
"""


def audit_primal_side_hypothesis(verified_rows):
	results=[]
	for row in verified_rows:
		if not row["locally_verified"]:
			continue
		primary=row["primary_finite"]
		neighbor=row["neighbor_finite"]
		observed=row["left_site_is_first"]
		predicted=(True if primary and not neighbor
			else False if neighbor and not primary else None)
		results.append({"edge_id":row["edge_id"],
			"primary_finite":primary,"neighbor_finite":neighbor,
			"local_index":row["local_index"],
			"neighbor_index":row["neighbor_index"],
			"observed_left_first":observed,
			"prediction_left_first":predicted,
			"prediction_matches":predicted==observed
				if predicted is not None else None,
			"status":"supported" if predicted==observed else
				"counterexample" if predicted is not None else "untested"})
	return results
