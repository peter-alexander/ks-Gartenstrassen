"""Read-only directed CGAL boundary fragments and adjacent face incidence.

Direction follows the counter-clockwise outer ring of the subject face,
so its interior lies to the left. Geometry on other faces is inspected
independently; no ownership is inferred from neighboring labels.
"""
from shapely.geometry import LineString
from shapely.geometry.polygon import orient


def directed_face_edges(polygons,labels,labelled_segments,*,face_ids=None,
		tolerance=1e-8,limit=40):
	if len(polygons)!=len(labels) or tolerance<=0 or limit<1:
		raise ValueError("Invalid directed boundary audit arguments")
	selected=range(len(polygons)) if face_ids is None else face_ids
	out=[]
	for face_id in selected:
		face=orient(polygons[face_id],sign=1.)
		ring=face.exterior
		coords=list(ring.coords)
		edges=[]
		for source_id,(line,pair) in enumerate(labelled_segments):
			for a,b in zip(coords,coords[1:]):
				ring_edge=LineString((a,b))
				overlap=ring_edge.intersection(line)
				if overlap.length<=tolerance:
					continue
				# Midpoint projection is used only to orient the overlap,
				# never to assign a site or match a source by proximity.
				fragments=(overlap.geoms if hasattr(overlap,"geoms")
					else (overlap,))
				for part in fragments:
					if not isinstance(part,LineString) or part.length<=tolerance:
						continue
					ends=list(part.coords)
					dx=b[0]-a[0]
					dy=b[1]-a[1]
					if ((ends[-1][0]-ends[0][0])*dx+
							(ends[-1][1]-ends[0][1])*dy)<0:
						ends.reverse()
					neighbors=[]
					for other_id,other in enumerate(polygons):
						if other_id==face_id:
							continue
						shared=part.intersection(other.boundary).length
						if shared>tolerance:
							neighbors.append({"face_index":other_id,
								"shared_length_m":shared,
								"generator_known":labels[other_id] is not None})
					edges.append({
						"source_index":source_id,
						"role":"".join(sorted(site[0] for site in pair)),
						"sites":[{"kind":site[0],"coordinates":list(site[1])}
							for site in sorted(pair,key=repr)],
						"start":list(ends[0]),"end":list(ends[-1]),
						"length_m":part.length,
						"neighbor_faces":neighbors})
		out.append({"face_index":face_id,
			"ring_orientation":"counterclockwise",
			"reported_edges":edges[:limit],
			"total_edges":len(edges),
			"without_neighbor":sum(not e["neighbor_faces"] for e in edges),
			"with_neighbor":sum(bool(e["neighbor_faces"]) for e in edges)})
	return out
