"""Fail-closed grouping of coincident endpoint duals (native diagnostics only).

A group is not a site ownership proof: a point and its adjoining
segments can share a geometric bisector while remaining different
native generator sites. The original edges and cell labels stay intact.
"""
from math import hypot


def _endpoint(pair):
	points=[s for s in pair if s[0]=="P"]
	segments=[s for s in pair if s[0]=="S"]
	if len(points)!=1 or len(segments)!=1:
		return None
	point,segment=points[0],segments[0]
	x,y=point[1]
	ax,ay,bx,by=segment[1]
	if (x,y) not in ((ax,ay),(bx,by)):
		return None
	return point,segment


def audit_coincident_endpoint_group(edge_ids,edges,rays,incidence,
		*,tolerance=1e-8):
	"""Return one classified group or reject malformed/ambiguous input."""
	sites={i:pair for i,pair,_ in edges}
	if len(edge_ids)!=2 or len(set(edge_ids))!=2:
		return {"status":"rejected","reason":"requires_two_distinct_edges"}
	records=[]
	for i in edge_ids:
		pair=sites.get(i)
		parsed=_endpoint(pair) if pair is not None else None
		directions=rays.get(i,[])
		info=incidence.get(i)
		if parsed is None or len(directions)!=1 or info is None:
			return {"status":"rejected","reason":"missing_native_endpoint_evidence"}
		x,y,u,v=directions[0]
		if hypot(u-x,v-y)<=tolerance:
			return {"status":"rejected","reason":"zero_direction"}
		if info["primary_finite"]==info["neighbor_finite"]:
			return {"status":"rejected","reason":"unexpected_primal_incidence"}
		records.append((i,parsed[0],parsed[1],(x,y,u-x,v-y),info))
	(i,p,s,(x,y,dx,dy),info),(j,p2,s2,(x2,y2,ex,ey),info2)=records
	if p!=p2 or s==s2:
		return {"status":"rejected","reason":"sites_not_point_two_segments"}
	if hypot(x-x2,y-y2)>tolerance or abs(dx*ey-dy*ex)>tolerance*max(1.,hypot(dx,dy)*hypot(ex,ey)) or dx*ex+dy*ey<=0:
		return {"status":"rejected","reason":"rays_not_codirected"}
	# The segments must meet only in their shared point, and extend
	# strictly to opposite sides of the directed ray.
	def side(segment):
		a,b=segment[1][:2],segment[1][2:]
		end=a if a!=p[1] else b
		return dx*(end[1]-p[1][1])-dy*(end[0]-p[1][0])
	side1,side2=side(s),side(s2)
	if abs(side1)<=tolerance or abs(side2)<=tolerance or side1*side2>=0:
		return {"status":"rejected","reason":"segments_not_opposite_ray_sides"}
	if info["opposite_sites"]!=info2["opposite_sites"]:
		return {"status":"rejected","reason":"primal_opposite_sites_differ"}
	return {"status":"grouped_diagnostic_only","edge_ids":list(edge_ids),
		"point_site":{"kind":"P","coordinates":list(p[1])},
		"left_segment":{"kind":"S","coordinates":list((s if side1>0 else s2)[1])},
		"right_segment":{"kind":"S","coordinates":list((s if side1<0 else s2)[1])},
		"primal_opposite_sites":info["opposite_sites"],
		"ownership_proven":False}
