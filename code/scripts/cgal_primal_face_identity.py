"""Validate optional native CGAL primal face-ID pairs.

Face IDs are identities within one native run only; neither cyclic order
nor Voronoi ownership follows from shared Delaunay face handles.
"""


def parse_primal_face_pairs(lines,expected_edges):
	if len(lines)!=expected_edges:
		raise ValueError("Primal face-pair count differs from labelled edges")
	rows={}
	for edge_id,line in enumerate(lines):
		parts=line.split()
		if (len(parts)!=4 or parts[:2]!=["H",str(edge_id)]
			or any(not value.isdecimal() for value in parts[2:])):
			raise ValueError("Malformed or reordered native face pair")
		first,second=map(int,parts[2:])
		if first==second:
			raise ValueError("Native edge has identical adjacent face handles")
		rows[edge_id]={"face_id":first,"neighbor_face_id":second}
	return rows


def audit_group_primal_faces(groups,face_pairs):
	report=[]
	for group in groups:
		ids=group.get("edge_ids",[])
		rows=[face_pairs.get(edge_id) for edge_id in ids]
		valid=(len(ids)==2 and len(set(ids))==2
			and group.get("status")=="grouped_diagnostic_only"
			and group.get("ownership_proven") is False
			and all(row is not None for row in rows))
		common=set(rows[0].values()).intersection(rows[1].values()) if valid else set()
		report.append({"edge_ids":list(ids),
			"status":"native_face_identity_observed_only" if valid
				else "blocked_incomplete_face_identity",
			"adjacent_face_ids":[{"edge_id":edge_id,**row}
				for edge_id,row in zip(ids,rows)] if valid else [],
			"shared_face_ids":sorted(common),
			"cyclic_order_proven":False,"ownership_proven":False})
	return report
