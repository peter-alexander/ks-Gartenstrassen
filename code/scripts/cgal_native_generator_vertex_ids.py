"""Parse immutable native Delaunay generator-vertex IDs per dual E record.

IDs are run-local CGAL vertex identities, not Voronoi face ownership.
"""


def parse_native_generator_ids(text):
	vertices={}
	edges={}
	for line in text.splitlines():
		parts=line.split()
		if not parts:
			continue
		if parts[0]=="V":
			if len(parts) not in (5,7) or parts[2] not in ("P","S"):
				raise ValueError("Invalid native vertex generator row")
			if (parts[2]=="P" and len(parts)!=5) or (parts[2]=="S" and len(parts)!=7):
				raise ValueError("Invalid generator coordinates")
			vertex=int(parts[1])
			if vertex in vertices:
				raise ValueError("Duplicate generator vertex ID")
			vertices[vertex]=(parts[2],tuple(float(v) for v in parts[3:]))
		elif parts[0]=="G":
			if len(parts)!=4:
				raise ValueError("Invalid native edge generator row")
			edge,a,b=map(int,parts[1:])
			if edge in edges or a==b:
				raise ValueError("Duplicate edge ID or self-edge")
			edges[edge]=(a,b)
		else:
			raise ValueError("Unexpected native generator row")
	if any(a not in vertices or b not in vertices for a,b in edges.values()):
		raise ValueError("Native generator ID not declared")
	return vertices,edges


def audit_native_generator_id_pairs(vertices,edge_ids,edge_sites):
	report=[]
	for eid,pair,_ in edge_sites:
		if eid not in edge_ids:
			raise ValueError("Missing native E generator identity")
		a,b=edge_ids[eid]
		def identity(site):
			return (site[0],tuple(float(v) for v in site[1]))
		if {identity(vertices[a]),identity(vertices[b])}!={identity(pair[0]),identity(pair[1])}:
			raise ValueError("Native generator ID and labelled E site mismatch")
		report.append({"edge_id":eid,"native_vertex_ids":[a,b],
			"status":"native_generator_vertex_ids_only_no_owner",
			"ownership_proven":False})
	if len(report)!=len(edge_ids):
		raise ValueError("Native edge identity count mismatch")
	return report
