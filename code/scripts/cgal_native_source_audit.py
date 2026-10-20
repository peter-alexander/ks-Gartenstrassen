"""Trace overlapping clipped CGAL fragments to their native E records.

Diagnostic only. Native fragment order must exactly match the flattened
metric adapter; inconsistent ordering is rejected, never guessed.
"""
from shapely.geometry import LineString
from scripts.build_cgal_voronoi_geojson import _record_line


def audit_native_shared_sources(shared_audit,native_edges,metric_segments,
		window,*,scale=1000.,tolerance=1e-8):
	native=[]
	for edge_id,pair,fragments in native_edges:
		for fragment_id,(kind,values) in enumerate(fragments):
			a=(values[0]/scale,values[1]/scale)
			b=(values[2]/scale,values[3]/scale)
			clipped=_record_line(kind,(a,b),window)
			if clipped is None or clipped.is_empty:
				continue
			for part in (clipped.geoms if hasattr(clipped,"geoms")
					else (clipped,)):
				if isinstance(part,LineString) and part.length>0:
					native.append((edge_id,fragment_id,kind,
						frozenset(pair),part))
	if len(native)!=len(metric_segments):
		raise ValueError("Native fragment count differs from metric adapter")
	for index,((_,_,_,pair,line),(actual,actual_pair)) in enumerate(
			zip(native,metric_segments)):
		if not line.equals_exact(actual,tolerance) or pair!=frozenset(actual_pair):
			raise ValueError(f"CGAL source order differs at fragment {index}")
	out=[]
	for row in shared_audit:
		if not row["multiply_labelled_spans"]:
			continue
		sources=sorted({source for span in row["atomic_spans"]
			if span["multiply_labelled"] for source in span["source_indices"]})
		records=[]
		for source in sources:
			edge_id,fragment_id,kind,pair,line=native[source]
			records.append({"metric_source_index":source,"edge_id":edge_id,
				"fragment_index":fragment_id,"fragment_kind":kind,
				"sites":[{"kind":s[0],"coordinates":list(s[1])}
					for s in sorted(pair,key=repr)],
				"clipped_bounds":list(line.bounds)})
		out.append({"face_indices":row["face_indices"],
			"shared_length_m":row["shared_length_m"],
			"overlapping_native_sources":records,
			"distinct_native_E_records":len({r["edge_id"] for r in records}),
			"distinct_generator_pairs":len({frozenset(
				(s["kind"],tuple(s["coordinates"])) for s in r["sites"])
				for r in records})})
	return out
