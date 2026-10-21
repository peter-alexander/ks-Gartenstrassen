"""Strict line-based diagnostic of native primal triangle vertex slots.

This is face-local source evidence, not cyclic ordering or Voronoi ownership.
"""


def parse_primal_face_vertices(lines,expected_edges,face_pairs):
	if len(lines)!=expected_edges:
		raise ValueError("Primal face-vertex record count mismatch")
	report={}
	for edge_id,line in enumerate(lines):
		pieces=line.split(" | FACE ")
		if len(pieces)!=3 or pieces[0]!=f"V {edge_id}":
			raise ValueError("Malformed native face vertex record")
		ids=[]
		for raw in pieces[1:]:
			tokens=raw.split(maxsplit=1)
			if len(tokens)!=2 or not tokens[0].isdecimal():
				raise ValueError("Missing native triangle vertex sites")
			face_id=int(tokens[0])
			slots=tokens[1]
			if not all(f" {i}:" in " "+slots for i in range(3)):
				raise ValueError("Missing triangle slot")
			ids.append(face_id)
		pair=face_pairs.get(edge_id)
		if pair is None or ids!=[pair["face_id"],pair["neighbor_face_id"]]:
			raise ValueError("Native triangle face identity mismatch")
		report[edge_id]={"face_ids":ids,"raw_slots":pieces[1:],
			"cyclic_order_proven":False,"ownership_proven":False}
	return report
