"""Adapt native labelled CGAL S/R/L records to metric clipped edges.

For small synthetic networks only: this is not a Vienna-scale polygonizer.
The same S/R/L clipping implementation as the existing debug exporter is
used, ensuring labelled and legacy geometry have identical semantics.
"""
import math
from pathlib import Path

from shapely.geometry import LineString

from scripts.cgal_labelled_edges import labelled_edges
from scripts.build_cgal_voronoi_geojson import _record_line
from scripts.cgal_segment_input import SCALE


def metric_labelled_segments(lines, window, origin=(0.,0.), scale=SCALE):
	"""Yield (metric LineString, (generator_a,generator_b)).

	Each native E record may have multiple S fragments (approximated
	parabola), or R/L records. All fragments retain the exact same pair.
	Degenerate or clipped-away fragments are skipped. Neither noding nor
	geometric ownership is inferred here.
	"""
	if scale<=0 or not math.isfinite(scale):
		raise ValueError("Invalid site coordinate scale")
	ox,oy=origin
	for edge_id,sites,fragments in labelled_edges(lines):
		for kind,values in fragments:
			a=(values[0]/scale+ox,values[1]/scale+oy)
			b=(values[2]/scale+ox,values[3]/scale+oy)
			try:
				clipped=_record_line(kind,(a,b),window)
			except ValueError as exc:
				raise ValueError(f"CGAL edge {edge_id}: {exc}") from exc
			if clipped is None or clipped.is_empty:
				continue
			for part in (clipped.geoms if hasattr(clipped,"geoms") else (clipped,)):
				if isinstance(part,LineString) and part.length>0:
					yield part,sites


def metric_labelled_segments_file(path, window, origin=(0.,0.), scale=SCALE):
	with Path(path).open(encoding="utf-8") as stream:
		yield from metric_labelled_segments(stream,window,origin,scale)


def reconstruct_native_test_cells(lines,window,origin=(0.,0.),scale=SCALE):
	"""Reconstruct labelled small-network cells; fail closed on missing labels."""
	from scripts.cgal_topology_proof import reconstruct_test_cells
	return reconstruct_test_cells(window,list(metric_labelled_segments(
		lines,window,origin,scale)))
