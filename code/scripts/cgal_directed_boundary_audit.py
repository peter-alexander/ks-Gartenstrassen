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


def audit_boundary_sides(polygons,labels,labelled_segments,*,face_ids=None,
		tolerance=1e-8):
	"""Cross-check directed left/right adjacency and native pair membership.

	Labels from previously proven neighboring faces are evidence only; an
	unknown face stays unknown. No nearest-site or side ownership inference.
	"""
	records=directed_face_edges(polygons,labels,labelled_segments,
		face_ids=face_ids,tolerance=tolerance,limit=100000)
	result=[]
	for face in records:
		face_id=face["face_index"]
		edges=[]
		for edge in face["reported_edges"]:
			pair={(site["kind"],tuple(site["coordinates"]))
				for site in edge["sites"]}
			left=labels[face_id]
			neighbors=[]
			for neighbor in edge["neighbor_faces"]:
				other_id=neighbor["face_index"]
				right=labels[other_id]
				neighbors.append({"face_index":other_id,
					"right_label_known":right is not None,
					"right_label_in_pair":right in pair if right is not None else None,
					"left_label_in_pair":left in pair if left is not None else None,
					"both_labels_in_pair":({left,right}==pair)
						if left is not None and right is not None else None})
			edges.append({"source_index":edge["source_index"],
				"role":edge["role"],"start":edge["start"],"end":edge["end"],
				"left_face_index":face_id,"left_label_known":left is not None,
				"neighbor_checks":neighbors})
		result.append({"face_index":face_id,"edge_checks":edges,
			"known_neighbor_checks":sum(n["right_label_known"]
				for e in edges for n in e["neighbor_checks"]),
			"neighbor_label_mismatches":sum(
				n["right_label_in_pair"] is False
				for e in edges for n in e["neighbor_checks"])})
	return result
