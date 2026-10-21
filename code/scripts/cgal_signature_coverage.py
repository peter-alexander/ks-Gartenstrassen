"""Aggregate verified regular CGAL primal signatures across native fixtures.

This report counts observations, including contradictions, and never infers
endpoint-dual site ownership. Every fixture must be represented explicitly.
"""
from collections import defaultdict

FIXTURES=("parallel","junction","crossing","oblique","fan","grid","near_parallel")


def audit_signature_coverage(results):
	if len(results)!=len(FIXTURES) or {r.get("fixture") for r in results}!=set(FIXTURES):
		raise ValueError("Expected exactly the seven distinct native fixtures")
	by_signature=defaultdict(lambda: {"left_first":[],"right_first":[]})
	for fixture in results:
		rows=fixture.get("experimental_carried",{}).get("primal_side_comparison")
		if not isinstance(rows,list):
			raise ValueError("Missing native regular comparison data")
		for row in rows:
			if row.get("locally_verified") is not True or type(row.get("left_site_is_first")) is not bool:
				continue
			keys=("local_index","neighbor_index")
			if any(type(row.get(k)) is not int or row[k] not in (0,1,2) for k in keys):
				raise ValueError("Malformed local primal index")
			if any(type(row.get(k)) is not bool for k in ("primary_finite","neighbor_finite")):
				raise ValueError("Malformed primal finiteness")
			sig=(row["local_index"],row["neighbor_index"],row["primary_finite"],row["neighbor_finite"])
			bucket=by_signature[sig]["left_first" if row["left_site_is_first"] else "right_first"]
			bucket.append({"fixture":fixture["fixture"],"edge_id":row["edge_id"]})
		return_rows=None
	out=[]
	for sig,observations in sorted(by_signature.items()):
		left=observations["left_first"]
		right=observations["right_first"]
		out.append({"signature":list(sig),"left_first":left,"right_first":right,
			"status":"contradictory_regular_observations" if left and right else "one_sided_observations_only",
			"ownership_proven":False})
	return {"fixtures":list(FIXTURES),"verified_regular_edges":sum(
		len(row["left_first"])+len(row["right_first"]) for row in out),
		"signatures":out,"ownership_proven":False}
