"""Check whether repeated native face handles have identical triangle slot exports.

This compares identical native face identities only, not geometric owner sides
or cyclic Delaunay circulation around a vertex.
"""


def audit_shared_face_slots(face_vertices,face_chain):
	by_face={}
	for edge_id,row in face_vertices.items():
		ids=row.get("face_ids",[])
		slots=row.get("raw_slots",[])
		if len(ids)!=2 or len(slots)!=2:
			raise ValueError("Incomplete native triangle slots")
		for face_id,raw in zip(ids,slots):
			if not isinstance(raw,str) or not raw.startswith(f"{face_id} "):
				raise ValueError("Face slot identity mismatch")
			value=raw[len(str(face_id))+1:]
			if face_id in by_face and by_face[face_id]!=value:
				raise ValueError("Conflicting site slots for identical native face handle")
			by_face[face_id]=value
	report=[]
	for chain in face_chain:
		links=chain.get("shared_with_third",[])
		ids=chain.get("edge_ids",[])
		third=chain.get("third_edge_id")
		valid=(chain.get("status")=="native_face_chain_confirmed_not_ownership"
			and chain.get("ownership_proven") is False
			and chain.get("cyclic_order_proven") is False
			and len(ids)==2 and len(links)==2
			and {link.get("edge_id") for link in links}==set(ids))
		if valid:
			for link in links:
				a,b=face_vertices.get(link["edge_id"]),face_vertices.get(third)
				fid=link.get("face_id")
				if a is None or b is None or fid not in a["face_ids"] or fid not in b["face_ids"]:
					valid=False
					break
		report.append({"edge_ids":list(ids),
			"third_edge_id":third,
			"status":"shared_native_triangle_slots_identical_only" if valid
				else "blocked_missing_shared_triangle_slots",
			"shared_face_ids":[link["face_id"] for link in links] if valid else [],
			"cyclic_order_proven":False,"ownership_proven":False})
	return report
