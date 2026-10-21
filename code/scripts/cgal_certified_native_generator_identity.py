"""Read-only link between distance-certified faces and native CGAL site vertices.

CGAL Delaunay vertices correspond to generating sites, not to the
ownership of reconstructed Voronoi polygon faces.
"""


def audit_certified_native_generator_identity(bounds,candidates,vertices,edge_ids):
	by_candidate={row["face_index"]:row for row in candidates
		if row.get("status")=="candidate_only_not_proven"}
	report=[]
	for row in bounds:
		if row.get("status")!="full_area_distance_bound_verified_only" or row.get("unknown_area_m2")!=0:
			continue
		fid=row["face_index"]
		if fid not in by_candidate or row.get("ownership_proven") is not False:
			raise ValueError("Missing safe distance-certified candidate")
		candidate=by_candidate[fid]["candidate_site"]
		key=(candidate["kind"],tuple(candidate["coordinates"]))
		matched=sorted(vid for vid,site in vertices.items()
			if (site[0],tuple(site[1]))==(key[0],tuple(float(x) for x in key[1])))
		if len(matched)!=1:
			raise ValueError("Candidate not uniquely represented by native CGAL generator vertex")
		vid=matched[0]
		incident=sorted(eid for eid,pair in edge_ids.items() if vid in pair)
		if not incident:
			raise ValueError("Native generating vertex has no incident E record")
		report.append({"face_index":fid,"native_generator_vertex_id":vid,
			"native_incident_edge_ids":incident,
			"status":"distance_certified_native_site_identity_only",
			"ownership_proven":False,"voronoi_side_proven":False})
	return report
