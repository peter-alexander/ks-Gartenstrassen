"""Read-only local-side comparison on overlapping native endpoint rays.

The native Delaunay-site orientation hypothesis is kept separate from the
verified polygon side. Neither constitutes a new CGAL ownership proof.
"""
from shapely.geometry import LineString,Point


def audit_endpoint_ray_local_sides(polygons,labels,candidate_rows,
		degenerate_rows,edges,rays,incidence,window,*,tolerance=1e-8):
	edge_sites={edge_id:pair for edge_id,pair,_ in edges}
	candidates={row["face_index"]:row["candidate_site"]
		for row in candidate_rows if row["status"]=="candidate_only_not_proven"}
	report=[]
	for row in degenerate_rows:
		faces=row["face_indices"]
		if len(faces)!=2 or any(index not in candidates for index in faces):
			continue
		edge_ids=row["native_edge_ids"]
		if len(edge_ids)!=2 or any(len(rays.get(e,[]))!=1 for e in edge_ids):
			continue
		raw=[rays[e][0] for e in edge_ids]
		x0,y0,x1,y1=raw[0]
		dx,dy=x1-x0,y1-y0
		length=(dx*dx+dy*dy)**.5
		if length<=tolerance:
			continue
		# Two overlapping rays must be codirected with the same source.
		if any((abs(r[0]-x0)>tolerance or abs(r[1]-y0)>tolerance
				or abs((r[2]-r[0])*dy-(r[3]-r[1])*dx)>tolerance
				or (r[2]-r[0])*dx+(r[3]-r[1])*dy<=0)
				for r in raw[1:]):
			continue
		shared=polygons[faces[0]].boundary.intersection(
			polygons[faces[1]].boundary)
		forward=LineString(((x0,y0),(x0+dx*1e7,y0+dy*1e7)))
		common=shared.intersection(forward.intersection(window))
		if common.length<=tolerance:
			continue
		piece=max(_lines(common),key=lambda g:g.length,default=None)
		if piece is None:
			continue
		mid=piece.interpolate(.5,normalized=True)
		nx,ny=-dy/length,dx/length
		sides=None
		for distance in (.0001,.001,.01):
			left=Point(mid.x+nx*distance,mid.y+ny*distance)
			right=Point(mid.x-nx*distance,mid.y-ny*distance)
			a,b=faces
			if polygons[a].contains(left) and polygons[b].contains(right):
				sides=(a,b)
				break
			if polygons[b].contains(left) and polygons[a].contains(right):
				sides=(b,a)
				break
		if sides is None:
			continue
		native=[]
		for edge_id in edge_ids:
			pair=edge_sites[edge_id]
			info=incidence[edge_id]
			# Both original vertex sites participate in the bisector,
			# but do not by themselves identify ownership on either side.
			predicted=("left" if info["primary_finite"] and not info["neighbor_finite"]
				else "right" if info["neighbor_finite"] and not info["primary_finite"]
				else None)
			native.append({"edge_id":edge_id,
				"first_site":{"kind":pair[0][0],"coordinates":list(pair[0][1])},
				"predicted_first_site_side":predicted,
				"candidate_on_left":candidates[sides[0]] in (
					{"kind":site[0],"coordinates":list(site[1])} for site in pair),
				"candidate_on_right":candidates[sides[1]] in (
					{"kind":site[0],"coordinates":list(site[1])} for site in pair),
				"first_site_matches_left_candidate":
					(pair[0][0],list(pair[0][1]))==(
						candidates[sides[0]]["kind"],candidates[sides[0]]["coordinates"]),
				"first_site_matches_right_candidate":
					(pair[0][0],list(pair[0][1]))==(
						candidates[sides[1]]["kind"],candidates[sides[1]]["coordinates"])})
		report.append({"face_indices":faces,"left_face":sides[0],
			"right_face":sides[1],"shared_forward_m":common.length,
			"candidate_left":candidates[sides[0]],
			"candidate_right":candidates[sides[1]],
			"native_edges":native,"ownership_proven":False})
	return report


def _lines(geometry):
	if geometry.geom_type=="LineString":
		yield geometry
	elif hasattr(geometry,"geoms"):
		for child in geometry.geoms:
			yield from _lines(child)
