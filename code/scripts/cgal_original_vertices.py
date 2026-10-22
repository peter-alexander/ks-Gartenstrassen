"""Classify native CGAL point sites by ORIGINAL LINEAR_USE vertex position.

Use only the source LineString's own ordered vertices, NEVER points added
by GEOS noding. All coordinates share the integer millimetre grid/origin
used when feeding CGAL.

An unambiguous inner original vertex inherits exactly that LINEAR_USE
edge_id. Original first/last endpoints, frame corners, noding-only sites,
and vertices found in multiple distinct original edge_ids stay omitted.
"""
from collections import Counter, defaultdict

from scripts.cgal_segment_input import SCALE


def original_inner_point_owners(records,origin):
	ox,oy=origin
	original_inner=defaultdict(set)
	all_vertices=defaultdict(set)
	endpoints=defaultdict(set)
	stats=Counter()
	for _object_id,edge_id,line in records:
		edge_id=str(edge_id)
		vertices=[]
		for coord in line.coords:
			p=(round((coord[0]-ox)*SCALE),
				round((coord[1]-oy)*SCALE))
			if vertices and vertices[-1]==p:
				stats["consecutive_vertices_collapsed_to_mm"]+=1
				continue
			vertices.append(p)
		if len(vertices)<2:
			raise ValueError(f"{edge_id}: original line has fewer than two mm-grid vertices")
		stats["source_features"]+=1
		stats["original_interior_vertex_occurrences"]+=max(0,len(vertices)-2)
		for point in vertices:
			all_vertices[point].add(edge_id)
		for point in (vertices[0],vertices[-1]):
			endpoints[point].add(edge_id)
		for point in vertices[1:-1]:
			original_inner[point].add(edge_id)
	# An identical source point associated with more than one line has
	# no unique LINEAR_USE edge_id in CGAL. Never make one up.
	owners={}
	for point,ids in original_inner.items():
		if len(all_vertices[point])>1 or len(ids)!=1 or point in endpoints:
			stats["ambiguous_or_endpoint_coincident_vertices_omitted"]+=1
			continue
		owners[point]=next(iter(ids))
	stats["unique_inner_original_vertices"]=len(owners)
	stats["distinct_original_endpoint_coordinates"]=len(endpoints)
	stats["distinct_original_interior_coordinates"]=len(original_inner)
	return owners,dict(stats)
