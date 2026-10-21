"""Independent geometric distance witnesses across coincident native rays.

Finite sample points can support local ordering, never global polygon ownership.
"""
from math import hypot,isfinite
from shapely.geometry import Point,LineString
from scripts.cgal_unresolved_site_audit import _metric_site


def audit_coincident_ray_distance_witness(polygons,sides,rays,*,scale=1000.,offsets=(.001,.01,.1),tolerance=1e-8):
	report=[]
	for row in sides:
		left_id,right_id=row["left_face"],row["right_face"]
		a,b=row["candidate_left"],row["candidate_right"]
		ids=[edge["edge_id"] for edge in row["native_edges"]]
		valid=(row.get("ownership_proven") is False and len(ids)==2
			and len(set(ids))==2 and 0<=left_id<len(polygons)
			and 0<=right_id<len(polygons) and left_id!=right_id)
		witnesses=[]
		if valid:
			r=[rays.get(i,[]) for i in ids]
			valid=all(len(x)==1 for x in r)
		if valid:
			x,y,x2,y2=r[0][0]
			dx,dy=x2-x,y2-y
			n=hypot(dx,dy)
			valid=n>tolerance and all(isfinite(t) for t in (x,y,dx,dy))
			if valid:
				valid=all(hypot(q[0]-x,q[1]-y)<tolerance
					and abs((q[2]-q[0])*dy-(q[3]-q[1])*dx)<tolerance
					and (q[2]-q[0])*dx+(q[3]-q[1])*dy>0 for q in [r[1][0]])
		if valid:
			shared=polygons[left_id].boundary.intersection(polygons[right_id].boundary)
			from shapely.geometry import LineString
			forward=LineString([(x,y),(x+dx/n*1e6,y+dy/n*1e6)])
			matching=shared.intersection(forward)
			parts=[matching] if matching.geom_type=="LineString" else list(getattr(matching,"geoms",()))
			parts=[part for part in parts if part.geom_type=="LineString" and part.length>tolerance]
			valid=bool(parts)
		if valid:
			mid=max(parts,key=lambda part:part.length).interpolate(.5,normalized=True)
			nx,ny=-dy/n,dx/n
			try:
				ga=_metric_site((a["kind"],tuple(a["coordinates"])),scale)
				gb=_metric_site((b["kind"],tuple(b["coordinates"])),scale)
			except (KeyError,TypeError,ValueError):
				valid=False
		if valid:
			for off in offsets:
				if not isfinite(off) or off<=0:
					valid=False
					break
				lp=Point(mid.x+nx*off,mid.y+ny*off)
				rp=Point(mid.x-nx*off,mid.y-ny*off)
				if not polygons[left_id].contains(lp) or not polygons[right_id].contains(rp):
					continue
				l_a,l_b=lp.distance(ga),lp.distance(gb)
				r_a,r_b=rp.distance(ga),rp.distance(gb)
				witnesses.append({"offset_m":off,"left_minus_right_candidate_m":l_a-l_b,
					"right_minus_left_candidate_m":r_b-r_a,
					"left_candidate_closer":l_a+l_b*0<l_b-tolerance,
					"right_candidate_closer":r_b<r_a-tolerance})
			valid=bool(witnesses)
		report.append({"face_indices":[left_id,right_id],
			"status":"finite_distance_samples_recorded_only" if valid else "blocked_distance_witness",
			"witnesses":witnesses if valid else [],
			"ownership_proven":False})
	return report
