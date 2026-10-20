"""Calibrate native CGAL ordered generator sites against proven face sides.

Only straight native rays are used. Each calibration requires two distinct,
already-proven face labels matching the exact pair on the native E record.
Endpoint duals and ambiguous overlaps never train the orientation rule.
"""
from shapely.geometry import LineString
from scripts.cgal_endpoint_dual_candidates import is_endpoint_pair


def audit_directed_side_calibration(polygons,labels,edges,rays,*,scale=1000.,
		tolerance=1e-8):
	if len(polygons)!=len(labels) or tolerance<=0:
		raise ValueError("Invalid directed site calibration")
	results=[]
	for edge_id,pair,_ in edges:
		if is_endpoint_pair(pair):
			continue
		for ray in rays.get(edge_id,[]):
			x0,y0,x1,y1=ray
			dx,dy=x1-x0,y1-y0
			if dx*dx+dy*dy<=tolerance*tolerance:
				continue
			line=LineString(((x0,y0),(x1,y1)))
			matches=[]
			for i,polygon in enumerate(polygons):
				if labels[i] not in pair:
					continue
				if polygon.boundary.intersection(line).length<=tolerance:
					# Ray may start outside the test window; its infinite
					# continuation is needed to check the clipped segment.
					from shapely.geometry import LineString as L
					end=L([(x0,y0),(x0+dx*1e6,y0+dy*1e6)])
					if polygon.boundary.intersection(end).length<=tolerance:
						continue
				point=polygon.representative_point()
				cross=dx*(point.y-y0)-dy*(point.x-x0)
				if abs(cross)<=tolerance:
					continue
				matches.append((i,labels[i],"left" if cross>0 else "right"))
			left={site for _,site,side in matches if side=="left"}
			right={site for _,site,side in matches if side=="right"}
			if len(left)!=1 or len(right)!=1 or left==right:
				continue
			l=next(iter(left))
			r=next(iter(right))
			if {l,r}!=set(pair):
				continue
			results.append({"edge_id":edge_id,
				"left_site_matches_first":l==pair[0],
				"right_site_matches_first":r==pair[0],
				"left_faces":[i for i,s,side in matches if side=="left" and s==l],
				"right_faces":[i for i,s,side in matches if side=="right" and s==r]})
	return results
