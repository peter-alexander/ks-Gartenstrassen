"""Read-only CGAL primal triangle neighbor-slot export validation.

Each slot links to a native neighboring Delaunay face; no Voronoi
generator ownership or cyclic ordering is inferred.
"""


def parse_primal_face_neighbors(lines,expected_edges,face_pairs):
	if len(lines)!=expected_edges:
		raise ValueError("Primal neighbor record count differs from edges")
	faces={}
	for edge_id,line in enumerate(lines):
		pieces=line.split(" | FACE ")
		if len(pieces)!=3 or pieces[0]!=f"N {edge_id}":
			raise ValueError("Malformed primal neighbor record")
		expected=face_pairs.get(edge_id)
		if expected is None:
			raise ValueError("Missing edge face identity")
		ids=[expected["face_id"],expected["neighbor_face_id"]]
		for i,chunk in enumerate(pieces[1:]):
			parts=chunk.split()
			if len(parts)!=4 or parts[0]!=str(ids[i]):
				raise ValueError("Primal neighbor face identity mismatch")
			neighbors=[]
			for slot,item in enumerate(parts[1:]):
				key,sep,value=item.partition(":")
				if not sep or key!=str(slot) or not value.isdecimal():
					raise ValueError("Malformed primal neighbor slot")
				neighbors.append(int(value))
			face_id=ids[i]
			if face_id in faces and faces[face_id]!=neighbors:
				raise ValueError("Conflicting native neighbor slots for same face")
			if face_id in neighbors:
				raise ValueError("Face neighbors itself")
			faces[face_id]=neighbors
	for face_id,neighbors in faces.items():
		for slot,neighbor in enumerate(neighbors):
			if neighbor in faces and face_id not in faces[neighbor]:
				raise ValueError("Nonreciprocal native face neighbors")
	return {"faces":faces,"cyclic_order_proven":False,"ownership_proven":False}
