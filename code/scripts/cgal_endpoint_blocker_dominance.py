"""Explain distance-bound blockers using exact point-on-candidate-segment inclusion.

For any point on a segment site, distance(x,segment) <= distance(x,point)
for every x. This is non-strict dominance, not polygon ownership.
"""


def audit_endpoint_blocker_dominance(candidates,bounds):
	by_face={row["face_index"]:row for row in candidates
		if row.get("status")=="candidate_only_not_proven"}
	results=[]
	for row in bounds:
		fid=row["face_index"]
		candidate=by_face.get(fid,{}).get("candidate_site")
		if not candidate or candidate.get("kind")!="S" or len(candidate.get("coordinates",[]))!=4:
			raise ValueError("Expected unresolved segment candidate")
		x0,y0,x1,y1=candidate["coordinates"]
		dx,dy=x1-x0,y1-y0
		if dx==dy==0:
			raise ValueError("Degenerate candidate segment")
		classified=[]
		for blocker in row.get("unknown_area_by_limiting_site",[]):
			site=blocker["site"]
			related=False
			if site["kind"]=="P" and len(site["coordinates"])==2:
				x,y=site["coordinates"]
				cross=(x-x0)*dy-(y-y0)*dx
				dot=(x-x0)*dx+(y-y0)*dy
				related=cross==0 and 0<=dot<=dx*dx+dy*dy
			classified.append({"limiting_site":site,
				"unknown_area_m2":blocker["area_m2"],
				"point_on_candidate_segment":related,
				"non_strict_dominance_proven":related})
		related_area=sum(x["unknown_area_m2"] for x in classified
			if x["non_strict_dominance_proven"])
		results.append({"face_index":fid,"blockers":classified,
			"non_strict_related_area_m2":related_area,
			"status":"endpoint_point_distance_relation_recorded_only",
			"ownership_proven":False})
	return results
