"""Cross-reference unresolved polygon candidates with original CGAL vertex IDs.

This only links E provenance to run-local Delaunay generator identities.
It does not assign a Voronoi face owner.
"""


def audit_endpoint_generator_vertex_crosscheck(conflicts,vertices,edge_ids):
	report=[]
	for row in conflicts:
		fid=row["face_index"]
		candidate=row["candidate_site"]
		key=(candidate["kind"],tuple(float(v) for v in candidate["coordinates"]))
		if row["status"]!="coincident_endpoint_conflict_isolated_not_resolved":
			raise ValueError("Unclassified endpoint conflict")
		matches=row["matching_endpoint_sources"]
		opposites=row["conflicting_endpoint_sources"]
		if len(matches)!=1 or len(opposites)!=1:
			raise ValueError("Expected one matching and one conflicting E source")
		evidence=[]
		for kind,sources in (("matching",matches),("conflicting",opposites)):
			edge=sources[0]["edge_id"]
			if edge not in edge_ids:
				raise ValueError("Missing native E vertex identities")
			ids=edge_ids[edge]
			if len(ids)!=2 or any(vertex not in vertices for vertex in ids):
				raise ValueError("Invalid native E vertex identities")
			pair=[(vertices[vertex][0],tuple(vertices[vertex][1])) for vertex in ids]
			present=key in pair
			if present!=(kind=="matching"):
				raise ValueError("Native vertex identity disagrees with candidate conflict")
			evidence.append({"edge_id":edge,"source_role":kind,
				"native_vertex_ids":list(ids),
				"candidate_vertex_id":ids[pair.index(key)] if present else None})
		shared=set(evidence[0]["native_vertex_ids"]) & set(evidence[1]["native_vertex_ids"])
		if len(shared)!=1:
			raise ValueError("Coincident E pair must share one original generator vertex")
		report.append({"face_index":fid,"candidate_site":candidate,
			"source_vertex_evidence":evidence,
			"shared_native_vertex_id":next(iter(shared)),
			"status":"native_vertex_identity_crosschecked_no_owner",
			"ownership_proven":False})
	return report
