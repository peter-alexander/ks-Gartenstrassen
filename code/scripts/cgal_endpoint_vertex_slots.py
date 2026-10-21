"""Find the native point-site vertex slot in each incident Delaunay face.

Original CGAL slot membership is evidence of incidence only, not a
circulator traversal, cyclic order, or Voronoi generator ownership.
"""
import re

_SLOT=re.compile(r"(?:^| )([012]):")
def _site_slots(raw):
	parts=raw.split(" ",1)
	if len(parts)!=2 or not parts[0].isdecimal():
		raise ValueError("Malformed native face slot header")
	payload=parts[1]
	matches=list(_SLOT.finditer(payload))
	if len(matches)!=3 or [int(m.group(1)) for m in matches]!=[0,1,2]:
		raise ValueError("Malformed native face vertex slots")
	return [payload[m.end():matches[i+1].start() if i<2 else len(payload)].strip()
		for i,m in enumerate(matches)]

def audit_endpoint_vertex_slots(stars,face_pairs,face_vertices):
	results=[]
	for star in stars:
		point=star.get("point_site",{})
		coords=point.get("coordinates",[])
		edges=star.get("incident_edges",[])
		valid=(star.get("status")=="native_incident_star_unordered_only"
			and star.get("ownership_proven") is False
			and star.get("cyclic_order_proven") is False
			and point.get("kind")=="P" and len(coords)==2
			and len(edges)==3 and len({e.get("edge_id") for e in edges})==3)
		observations={}
		if valid:
			for edge in edges:
				eid=edge["edge_id"]
				pair,vertices=face_pairs.get(eid),face_vertices.get(eid)
				if pair is None or vertices is None:
					valid=False
					break
				expected=[pair["face_id"],pair["neighbor_face_id"]]
				if vertices.get("face_ids")!=expected:
					valid=False
					break
				for face_id,raw in zip(expected,vertices["raw_slots"]):
					try:
						sites=_site_slots(raw)
						hits=[i for i,site in enumerate(sites)
							if site.startswith("P ") and len(site.split())==3
							and [float(x) for x in site.split()[1:]]==
								[float(x) for x in coords]]
					except (ValueError,TypeError):
						valid=False
						break
					if len(hits)!=1 or (face_id in observations
						and observations[face_id]!=hits[0]):
						valid=False
						break
					observations[face_id]=hits[0]
				if not valid:
					break
		results.append({"edge_ids":star.get("edge_ids",[]),
			"status":"native_point_vertex_slots_observed_only" if valid
				else "blocked_ambiguous_or_missing_point_vertex_slot",
			"face_vertex_slots":[{"face_id":fid,"vertex_slot":slot}
				for fid,slot in sorted(observations.items())] if valid else [],
			"cyclic_order_proven":False,"ownership_proven":False})
	return results
