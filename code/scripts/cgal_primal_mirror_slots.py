"""Check CGAL primal edge indices against original triangle neighbor slots.

A mirrored face-slot match establishes local primal adjacency only.
It is not a cyclic point-site rotation or Voronoi ownership proof.
"""


def audit_primal_mirror_slots(face_pairs,incidence,neighbor_export):
	faces=neighbor_export.get("faces")
	if not isinstance(faces,dict) or neighbor_export.get("ownership_proven") is not False:
		raise ValueError("Invalid native neighbor export")
	if set(face_pairs)!=set(incidence):
		raise ValueError("Incomplete native edge/face incidence")
	report=[]
	for edge_id,pair in sorted(face_pairs.items()):
		row=incidence[edge_id]
		a,b=pair["face_id"],pair["neighbor_face_id"]
		i,j=row["local_index"],row["neighbor_index"]
		if (type(i) is not int or type(j) is not int or i not in range(3)
			or j not in range(3) or a not in faces or b not in faces
			or len(faces[a])!=3 or len(faces[b])!=3):
			raise ValueError("Incomplete native primal slot evidence")
		if faces[a][i]!=b or faces[b][j]!=a:
			raise ValueError(f"Native mirror slot mismatch at E{edge_id}")
		report.append({"edge_id":edge_id,"face_id":a,"local_index":i,
			"neighbor_face_id":b,"mirror_index":j,
			"status":"native_mirror_slot_consistent_only",
			"cyclic_order_proven":False,"ownership_proven":False})
	return report
