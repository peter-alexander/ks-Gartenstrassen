"""Conservative whole-area distance bounds for unresolved native CGAL faces.

Rectangle corner maxima bound candidate point-to-site distance from above:
distance to a convex point/segment site is convex. Rectangle-to-site
minimum bounds any competing generator distance from below. A tile is
certified only if every competitor's lower bound exceeds the candidate
upper bound. Uncertified tiles remain explicitly unknown.
"""
from math import isfinite
from shapely.geometry import box,Point
from scripts.cgal_unresolved_site_audit import _metric_site


def audit_unresolved_area_distance_bounds(polygons,labels,edges,candidates,
		*,scale=1000.,max_depth=3,tolerance=1e-9):
	if len(polygons)!=len(labels) or not 0<=max_depth<=8 or scale<=0 or tolerance<0:
		raise ValueError("Invalid area distance bound parameters")
	sites=sorted({site for _,pair,_ in edges for site in pair},key=repr)
	geometries={site:_metric_site(site,scale) for site in sites}
	rows=[]
	for item in candidates:
		if item.get("status")!="candidate_only_not_proven":
			continue
		index=item["face_index"]
		if not isinstance(index,int) or index<0 or index>=len(polygons) or labels[index] is not None:
			raise ValueError("Candidate must reference an unresolved polygon")
		site=item.get("candidate_site")
		if not isinstance(site,dict):
			raise ValueError("Missing candidate site")
		key=(site.get("kind"),tuple(site.get("coordinates",())))
		if key not in geometries:
			raise ValueError("Candidate site absent from native generator set")
		polygon=polygons[index]
		candidate=geometries[key]
		others=[geom for other,geom in geometries.items() if other!=key]
		checked=0
		certified_area=0.
		unknown_area=0.
		deepest=0
		def visit(xmin,ymin,xmax,ymax,depth):
			nonlocal checked,certified_area,unknown_area,deepest
			tile=box(xmin,ymin,xmax,ymax)
			part=polygon.intersection(tile)
			if part.is_empty or part.area<=0:
				return
			checked+=1
			deepest=max(deepest,depth)
			corners=(Point(xmin,ymin),Point(xmin,ymax),
				Point(xmax,ymin),Point(xmax,ymax))
			max_candidate=max(point.distance(candidate) for point in corners)
			certified=all(tile.distance(other)>max_candidate+tolerance for other in others)
			if certified:
				certified_area+=part.area
			elif depth==max_depth or xmin==xmax or ymin==ymax:
				unknown_area+=part.area
			else:
				xmid=(xmin+xmax)*.5
				ymid=(ymin+ymax)*.5
				for a,b,c,d in ((xmin,ymin,xmid,ymid),
					(xmid,ymin,xmax,ymid),(xmin,ymid,xmid,ymax),
					(xmid,ymid,xmax,ymax)):
					visit(a,b,c,d,depth+1)
		visit(*polygon.bounds,0)
		area=polygon.area
		full=(unknown_area<=tolerance and abs(certified_area-area)<=tolerance)
		rows.append({"face_index":index,"generator_count":len(sites),
			"tiles_checked":checked,"max_depth_reached":deepest,
			"certified_area_m2":certified_area,"unknown_area_m2":unknown_area,
			"status":"full_area_distance_bound_verified_only" if full
				else "partial_area_distance_bound_unknown",
			"ownership_proven":False})
	return rows
