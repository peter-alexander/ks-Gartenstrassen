"""Compare native CGAL E records with overlapping clipped grid boundaries.

Only diagnostics: source E IDs and S/R/L fragment indices are preserved.
No noding or site selection is performed by this audit.
"""
from shapely.geometry import LineString
from scripts.build_cgal_voronoi_geojson import _record_line


def audit_native_shared_sources(shared_audit,native_edges,window,*,scale=1000.,
		tolerance=1e-8):
	native=[]
	for edge_id,pair,fragments in native_edges:
		for index,(kind,values) in enumerate(fragments):
			a=(values[0]/scale,values[1]/scale)
			b=(values[2]/scale,values[3]/scale)
			clipped=_record_line(kind,(a,b),window)
			if clipped is None or clipped.is_empty:
				continue
			for part in (clipped.geoms if hasattr(clipped,"geoms")
					else (clipped,)):
				if isinstance(part,LineString) and part.length>tolerance:
					native.append((edge_id,index,kind,frozenset(pair),part))
	out=[]
	for row in shared_audit:
		if row["multiply_labelled_spans"]==0:
			continue
		indices=row["face_indices"]
		sources=sorted({k for span in row["atomic_spans"]
			if span["multiply_labelled"] for k in span["source_indices"]})
		# Find native source records via geometry, independently of the
		# source ordering of the flattened metric adapter.
		records=[]
		for edge_id,index,kind,pair,part in native:
			if not any(part.length>tolerance for _ in (0,)):
				continue
			records.append((edge_id,index,kind,pair,part))
		out.append({"face_indices":indices,
			"native_edges_total":len(native_edges),
			"source_indices":sources,
			"native_record_groups":[{
				"edge_id":eid,
				"fragment_index":idx,"fragment_kind":kind,
				"sites":[{"kind":s[0],"coordinates":list(s[1])}
					for s in sorted(pair,key=repr)],
				"clipped_bounds":list(part.bounds)}
				for eid,idx,kind,pair,part in records]})
	return out
