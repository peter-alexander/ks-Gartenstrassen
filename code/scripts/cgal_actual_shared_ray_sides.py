"""Audit calibrated CGAL ray sides using actual shared face boundaries.

Diagnostic only: the shared boundary is checked against the forward ray,
and opposite polygon interiors are sampled locally across that boundary.
No ownership labels are inferred or modified.
"""
from shapely.geometry import LineString,Point
from scripts.cgal_endpoint_dual_candidates import is_endpoint_pair


def audit_actual_shared_ray_sides(polygons,labels,edges,rays,window,
		*,tolerance=1e-8):
	out=[]
	for edge_id,pair,_ in edges:
		if is_endpoint_pair(pair):
			continue
		for ray in rays.get(edge_id,[]):
			x0,y0,x1,y1=ray
			dx,dy=x1-x0,y1-y0
			length=(dx*dx+dy*dy)**.5
			if length<=tolerance:
				continue
			forward=LineString(((x0,y0),(x0+dx*1e7,y0+dy*1e7)))
			clipped=forward.intersection(window)
			for i in range(len(polygons)):
				if labels[i] not in pair:
					continue
				for j in range(i+1,len(polygons)):
					if labels[j] not in pair or labels[i]==labels[j]:
						continue
					shared=polygons[i].boundary.intersection(polygons[j].boundary)
					overlap=shared.intersection(clipped)
					if overlap.length<=tolerance:
						continue
					part=max(_lines(overlap),key=lambda x:x.length,default=None)
					if part is None:
						continue
					mid=part.interpolate(.5,normalized=True)
					nx,ny=-dy/length,dx/length
					sides=[]
					for offset in (.0001,.001,.01):
						p_left=Point(mid.x+nx*offset,mid.y+ny*offset)
						p_right=Point(mid.x-nx*offset,mid.y-ny*offset)
						if polygons[i].contains(p_left) and polygons[j].contains(p_right):
							sides=[labels[i],labels[j]]
							break
						if polygons[j].contains(p_left) and polygons[i].contains(p_right):
							sides=[labels[j],labels[i]]
							break
					out.append({"edge_id":edge_id,"face_indices":[i,j],
						"shared_length_m":shared.length,
						"on_forward_ray_m":overlap.length,
						"locally_verified":bool(sides),
						"left_site_is_first":sides[0]==pair[0] if sides else None,
						"left_site":str(sides[0]) if sides else None,
						"right_site":str(sides[1]) if sides else None})
	return out


def _lines(geom):
	if geom.geom_type=="LineString":
		yield geom
	elif hasattr(geom,"geoms"):
		for part in geom.geoms:
			yield from _lines(part)
