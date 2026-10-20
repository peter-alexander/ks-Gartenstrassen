"""Diagnostic comparison of unresolved polygon faces to native CGAL sites.

A point site strictly inside an unresolved face is evidence that a polygon
may contain multiple cells. Boundary sites, by contrast, are not proof.
This module does not assign owners or modify the reconstructed geometry.
"""
from shapely.geometry import Point,LineString
from shapely.strtree import STRtree


def _metric_site(site,scale):
	kind,coords=site
	if kind=="P":
		return Point(coords[0]/scale,coords[1]/scale)
	return LineString(((coords[0]/scale,coords[1]/scale),
		(coords[2]/scale,coords[3]/scale)))


def inspect_unresolved_faces(polygons,labels,edges,*,scale=1000.,limit=12):
	if len(polygons)!=len(labels) or scale<=0 or limit<1:
		raise ValueError("Invalid site audit arguments")
	sites=set()
	for _,pair,_ in edges:
		sites.update(pair)
	ordered=sorted(sites,key=repr)
	geometries=[_metric_site(site,scale) for site in ordered]
	tree=STRtree(geometries)
	samples=[]
	for face_id,(polygon,label) in enumerate(zip(polygons,labels)):
		if label is not None:
			continue
		inside=[]
		boundary=[]
		for hit in tree.query(polygon):
			i=int(hit)
			geometry=geometries[i]
			if polygon.contains(geometry):
				inside.append(i)
			elif polygon.intersects(geometry):
				boundary.append(i)
		samples.append({
			"face_index":face_id,
			"area_m2":polygon.area,
			"strictly_contained_sites":len(inside),
			"boundary_intersecting_sites":len(boundary),
			"contained_site_types":{
				"P":sum(ordered[i][0]=="P" for i in inside),
				"S":sum(ordered[i][0]=="S" for i in inside)},
			"distinct_contained_generators":[
				{"kind":ordered[i][0],"coordinates":list(ordered[i][1])}
				for i in inside[:limit]],
			"multiple_contained_sites":len(inside)>1})
	return samples
