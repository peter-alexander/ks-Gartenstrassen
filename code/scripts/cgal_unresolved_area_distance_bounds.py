"""Conservative whole-area distance bounds for unresolved native CGAL faces.

Clipped polygon vertex maxima bound candidate point-to-site distance from above:
distance to a convex point/segment site is convex. Clipped-polygon-to-site
minimum bounds any competing generator distance from below. A tile is
certified only if every competitor's lower bound exceeds the candidate
upper bound. Uncertified tiles remain explicitly unknown.
"""
from shapely.geometry import box,Point
from scripts.cgal_unresolved_site_audit import _metric_site


def _vertices(geometry):
	if geometry.geom_type=="Polygon":
		for xy in geometry.exterior.coords:
			yield Point(xy)
		for interior in geometry.interiors:
			for xy in interior.coords:
				yield Point(xy)
	elif hasattr(geometry,"geoms"):
		for child in geometry.geoms:
			yield from _vertices(child)


def _point_on_candidate_segment(site,candidate):
	if candidate[0]!="S" or site[0]!="P":
		return False
	x,y=site[1]
	x0,y0,x1,y1=candidate[1]
	dx,dy=x1-x0,y1-y0
	if dx==dy==0:
		return False
	cross=(x-x0)*dy-(y-y0)*dx
	dot=(x-x0)*dx+(y-y0)*dy
	return cross==0 and 0<=dot<=dx*dx+dy*dy


def _shared_endpoint_behind_halfplane(candidate,other,vertices,scale):
	"""If all projections on the other segment point behind their common
	endpoint, its closest point is that endpoint everywhere in the polygon.
	The candidate contains that endpoint and is therefore no farther away.
	"""
	if candidate[0]!="S" or other[0]!="S":
		return False
	a,b=candidate[1][:2],candidate[1][2:]
	p,q=other[1][:2],other[1][2:]
	shared=set((a,b)) & set((p,q))
	if len(shared)!=1:
		return False
	end=next(iter(shared))
	far=q if p==end else p
	dx,dy=far[0]-end[0],far[1]-end[1]
	if dx==dy==0:
		return False
	return all((vertex.x*scale-end[0])*dx+(vertex.y*scale-end[1])*dy<=0
		for vertex in vertices)


def audit_unresolved_area_distance_bounds(polygons,labels,edges,candidates,
		*,scale=1000.,max_depth=3,tolerance=1e-9,diagnostic_limit=24):
	if len(polygons)!=len(labels) or not 0<=max_depth<=8 or scale<=0 or tolerance<0 or diagnostic_limit<0:
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
		dominated={site for site in sites if site!=key
			and _point_on_candidate_segment(site,key)}
		checked=0
		certified_area=0.
		unknown_area=0.
		deepest=0
		blockers=[]
		shared_endpoint_covered_area=0.
		blocked_area_by_site={}
		unknown_area_by_margin={"negative_bound":0.,"near_zero_bound":0.,"positive_but_insufficient":0.}
		def visit(xmin,ymin,xmax,ymax,depth):
			nonlocal checked,certified_area,unknown_area,deepest,shared_endpoint_covered_area
			tile=box(xmin,ymin,xmax,ymax)
			part=polygon.intersection(tile)
			if part.is_empty or part.area<=0:
				return
			checked+=1
			deepest=max(deepest,depth)
			vertices=list(_vertices(part))
			if not vertices:
				unknown_area+=part.area
				return
			max_candidate=max(point.distance(candidate) for point in vertices)
			shared_endpoint_dominated=[site for site in sites if site!=key
				and _shared_endpoint_behind_halfplane(key,site,vertices,scale)]
			competitors=[(part.distance(geom)-max_candidate,site)
				for site,geom in geometries.items() if site!=key and site not in dominated
				and not _shared_endpoint_behind_halfplane(key,site,vertices,scale)]
			margin,limiting=min(competitors,key=lambda pair:(pair[0],repr(pair[1]))) if competitors else (float('inf'),None)
			certified=margin>tolerance
			if certified and shared_endpoint_dominated:
				shared_endpoint_covered_area+=part.area
			if certified:
				certified_area+=part.area
			elif depth==max_depth or xmin==xmax or ymin==ymax:
				unknown_area+=part.area
				category=("negative_bound" if margin < -tolerance else
					"positive_but_insufficient" if margin>tolerance else "near_zero_bound")
				unknown_area_by_margin[category]+=part.area
				if limiting is not None:
					blocked_area_by_site[limiting]=blocked_area_by_site.get(limiting,0.)+part.area
					if len(blockers)<diagnostic_limit:
						blockers.append({'bounds_m':[xmin,ymin,xmax,ymax],
							'area_m2':part.area,'bound_margin_m':margin,
							'limiting_site':{'kind':limiting[0],
								'coordinates':list(limiting[1])}})
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
			"non_strict_dominated_site_count":len(dominated),
			"shared_endpoint_halfplane_covered_area_m2":shared_endpoint_covered_area,
			"non_strict_dominated_sites":[{"kind":s[0],"coordinates":list(s[1])}
				for s in sorted(dominated,key=repr)],
			"certified_area_m2":certified_area,"unknown_area_m2":unknown_area,
			"unknown_tile_examples":blockers,
			"unknown_area_by_margin_m2":unknown_area_by_margin,
			"unknown_area_by_limiting_site":[{"site":{"kind":site[0],"coordinates":list(site[1])},
				"area_m2":area} for site,area in sorted(blocked_area_by_site.items(),
				key=lambda item:(-item[1],repr(item[0])))],
			"status":"full_area_distance_bound_verified_only" if full
				else "partial_area_distance_bound_unknown",
			"ownership_proven":False})
	return rows
