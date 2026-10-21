"""Conservative census of original CGAL dual sources touching unresolved faces.

Boundary overlap is evidence of incidence, never of polygon ownership.
"""
from shapely.ops import unary_union
from scripts.build_cgal_voronoi_geojson import _record_line


def audit_unresolved_native_sources(polygons,labels,edges,window,*,scale=1000.,tolerance=1e-8):
	if len(polygons)!=len(labels) or scale<=0 or tolerance<=0:
		raise ValueError("Invalid unresolved-source census arguments")
	sources=[]
	for eid,pair,fragments in edges:
		for kind,coords in fragments:
			if kind not in ("S","R","L") or len(coords)!=4:
				raise ValueError("Invalid original CGAL primitive")
			xy=[value/scale for value in coords]
			geom=_record_line(kind,((xy[0],xy[1]),(xy[2],xy[3])),window)
			if geom is not None and not geom.is_empty:
				sources.append((eid,kind,frozenset(pair),geom))
	report=[]
	for index,(face,label) in enumerate(zip(polygons,labels)):
		if label is not None:
			continue
		inside=face.boundary.difference(window.boundary)
		rows=[]
		for eid,kind,pair,geom in sources:
			part=inside.intersection(geom)
			if part.length<=tolerance:
				continue
			rows.append({"edge_id":eid,"primitive_kind":kind,
				"intersection_length_m":part.length,
				"sites":[{"kind":site[0],"coordinates":list(site[1])}
					for site in sorted(pair,key=repr)]})
		pairs={frozenset((s["kind"],tuple(s["coordinates"])) for s in row["sites"])
			for row in rows}
		edge_ids={row["edge_id"] for row in rows}
		report.append({"face_index":index,"area_m2":face.area,
			"boundary_source_records":rows,
			"distinct_native_edges":len(edge_ids),
			"distinct_site_pairs":len(pairs),
			"covered_internal_boundary_m":unary_union([
				inside.intersection(geom) for _,_,_,geom in sources
				if inside.intersects(geom)]).length if sources else 0.,
			"status":"native_boundary_sources_only_no_owner",
			"ownership_proven":False})
	return report
