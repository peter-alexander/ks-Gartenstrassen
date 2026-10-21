"""Finite interior-point counterexample witnesses for uncertified distance tiles.

A strict competitor advantage at an interior point disproves global
candidate dominance. Absence of such a point never proves ownership.
"""
from shapely.geometry import Point,box
from scripts.cgal_unresolved_site_audit import _metric_site


def audit_unknown_tile_counterexamples(polygons,labels,edges,candidates,bounds,
		*,scale=1000.,tolerance=1e-8):
	if len(polygons)!=len(labels) or scale<=0 or tolerance<0:
		raise ValueError("Invalid distance witness parameters")
	sites={site:_metric_site(site,scale) for _,pair,_ in edges for site in pair}
	by_candidate={row["face_index"]:row for row in candidates
		if row.get("status")=="candidate_only_not_proven"}
	results=[]
	for row in bounds:
		fid=row["face_index"]
		if fid not in by_candidate or labels[fid] is not None:
			raise ValueError("Unknown face has no unresolved candidate")
		c=by_candidate[fid]["candidate_site"]
		key=(c["kind"],tuple(c["coordinates"]))
		if key not in sites:
			raise ValueError("Candidate missing from original sites")
		witnesses=[]
		checked=0
		for item in row.get("unknown_tile_examples",[]):
			part=polygons[fid].intersection(box(*item["bounds_m"]))
			if part.is_empty or part.area<=0:
				continue
			point=part.representative_point()
			if not polygons[fid].contains(point) or not part.contains(point):
				continue
			checked+=1
			cd=point.distance(sites[key])
			competitors=sorted(((point.distance(geom),site)
				for site,geom in sites.items() if site!=key),
				key=lambda record:(record[0],repr(record[1])))
			if not competitors:
				continue
			distance,site=competitors[0]
			if distance+tolerance<cd:
				witnesses.append({"point_m":[point.x,point.y],
					"candidate_distance_m":cd,"competitor_distance_m":distance,
					"competitor_site":{"kind":site[0],
						"coordinates":list(site[1])}})
		results.append({"face_index":fid,
			"tested_interior_points":checked,
			"counterexamples":witnesses,
			"status":"strict_distance_counterexample_found" if witnesses
				else "no_counterexample_in_finite_samples",
			"ownership_proven":False})
	return results
