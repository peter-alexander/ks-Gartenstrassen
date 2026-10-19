"""Deterministic geometric mean axis for LINEAR_USE lines sharing one edge_id.

This module deliberately knows nothing about GeoPackage tables or the Vienna
pipeline. It solves one geometric task only: given one or more LineStrings
known by an external key to represent the same longitudinal street section,
construct one representative mean axis.

Method:
- one input line is returned byte-for-byte geometrically unchanged;
- for multiple lines, choose the longest line as orientation reference;
- orient every other line to minimize correspondence distance to the reference;
- sample every oriented line at identical fractions of normalized arclength;
- at each fraction take the arithmetic mean of all XY coordinates;
- connect those mean points in order.

This is a sampled arithmetic mean axis, not a polygon medial-axis/skeleton.
No distance, angle, street-name or merge heuristic is used here.
"""
from dataclasses import dataclass
import math

from shapely import line_merge, union_all
from shapely.geometry import LineString


DEFAULT_SAMPLE_SPACING_M = 5.0
ALIGNMENT_SAMPLES = 21


@dataclass(frozen=True)
class MeanAxisAudit:
	method: str
	input_lines: int
	sample_points: int
	reversed_lines: int
	min_length_m: float
	max_length_m: float
	length_ratio_min_max: float
	max_correspondence_spread_m: float
	mean_correspondence_spread_m: float


def _validate_line(line, index):
	if not isinstance(line, LineString):
		raise TypeError(f"Linie {index}: LineString erwartet")
	if line.is_empty or not line.is_valid or line.length <= 0:
		raise ValueError(f"Linie {index}: leere, ungültige oder längenlose Geometrie")
	if not all(math.isfinite(value) for xy in line.coords for value in xy[:2]):
		raise ValueError(f"Linie {index}: nicht-endliche Koordinate")


def _point_xy(line, fraction, *, reverse=False):
	position=(1.0-fraction if reverse else fraction)
	point=line.interpolate(position,normalized=True)
	return point.x,point.y


def _alignment_cost(reference, candidate, *, reverse):
	total=0.0
	for i in range(ALIGNMENT_SAMPLES):
		fraction=i/(ALIGNMENT_SAMPLES-1)
		ax,ay=_point_xy(reference,fraction)
		bx,by=_point_xy(candidate,fraction,reverse=reverse)
		total+=math.hypot(ax-bx,ay-by)
	return total


def _orientation(reference, candidate):
	forward=_alignment_cost(reference,candidate,reverse=False)
	backward=_alignment_cost(reference,candidate,reverse=True)
	return backward < forward


def _sample_count(lines, spacing_m):
	if not math.isfinite(spacing_m) or spacing_m <= 0:
		raise ValueError("Abtastabstand muss positiv und endlich sein")
	# Include both endpoints. The longest member determines resolution so that
	# no member is represented more coarsely than requested.
	return max(2,math.ceil(max(line.length for line in lines)/spacing_m)+1)


def _spread(points):
	if len(points)<2:
		return 0.0
	maximum=0.0
	for i,(ax,ay) in enumerate(points):
		for bx,by in points[i+1:]:
			maximum=max(maximum,math.hypot(ax-bx,ay-by))
	return maximum



def build_edge_axes(records, *, sample_spacing_m=DEFAULT_SAMPLE_SPACING_M):
	"""Group (edge_id, LineString) records and build one axis per edge_id.

	Grouping is purely attributive. Geometry never decides whether two
	LINEAR_USE records belong together.
	"""
	groups={}
	for index,record in enumerate(records):
		try:
			edge_id,line=record
		except (TypeError,ValueError) as exc:
			raise ValueError(
				f"Datensatz {index}: genau (edge_id, LineString) erwartet") from exc
		edge_id=str(edge_id).strip() if edge_id is not None else ""
		if not edge_id:
			raise ValueError(f"Datensatz {index}: edge_id fehlt")
		_validate_line(line,index)
		groups.setdefault(edge_id,[]).append(line)
	if not groups:
		raise ValueError("Mindestens ein LINEAR_USE-Datensatz erforderlich")
	return {
		edge_id:build_mean_axis(lines,sample_spacing_m=sample_spacing_m)
		for edge_id,lines in sorted(groups.items())
	}

def build_mean_axis(lines, *, sample_spacing_m=DEFAULT_SAMPLE_SPACING_M):
	"""Return (mean_axis, audit) for already-grouped parallel/related lines.

	The function does NOT decide whether lines belong together. That must be
	established externally (for LINEAR_USE the intended key is edge_id).
	"""
	lines=tuple(lines)
	if not lines:
		raise ValueError("Mindestens eine Linie erforderlich")
	for index,line in enumerate(lines):
		_validate_line(line,index)
	lengths=[line.length for line in lines]
	if len(lines)==1:
		line=lines[0]
		return line,MeanAxisAudit(
			method="single",
			input_lines=1,
			sample_points=len(line.coords),
			reversed_lines=0,
			min_length_m=line.length,
			max_length_m=line.length,
			length_ratio_min_max=1.0,
			max_correspondence_spread_m=0.0,
			mean_correspondence_spread_m=0.0,
		)

	# LINEAR_USE can contain several consecutive pieces with the same edge_id.
	# If their exact linework forms one single chain, preserve that source
	# geometry and merely merge the pieces. No tolerance or proximity heuristic.
	merged=line_merge(union_all(lines))
	if isinstance(merged,LineString) and (
			not merged.is_empty and merged.is_valid and merged.is_simple
			and merged.length>0
	):
		return merged,MeanAxisAudit(
			method="line_merge",
			input_lines=len(lines),
			sample_points=len(merged.coords),
			reversed_lines=0,
			min_length_m=min(lengths),
			max_length_m=max(lengths),
			length_ratio_min_max=min(lengths)/max(lengths),
			max_correspondence_spread_m=0.0,
			mean_correspondence_spread_m=0.0,
		)

	# Longest geometry is stable for unequal lengths and gives curved shorter
	# members the broadest available directional reference. Ties intentionally
	# preserve caller order; this can only reverse the resulting line, not
	# change its geometric locus for consistently corresponding members.
	reference=max(enumerate(lines),key=lambda item:(item[1].length,-item[0]))[1]
	reversed_flags=[False if line is reference else _orientation(reference,line)
		for line in lines]
	count=_sample_count(lines,sample_spacing_m)
	coordinates=[]
	spreads=[]
	for number in range(count):
		fraction=number/(count-1)
		points=[
			_point_xy(line,fraction,reverse=reverse)
			for line,reverse in zip(lines,reversed_flags)
		]
		x=sum(point[0] for point in points)/len(points)
		y=sum(point[1] for point in points)/len(points)
		coordinates.append((x,y))
		spreads.append(_spread(points))
	axis=LineString(coordinates)
	if axis.is_empty or not axis.is_valid or not axis.is_simple or axis.length<=0:
		raise ValueError(
			"Aus den gruppierten Linien entsteht keine einfache gültige Mittelachse")
	return axis,MeanAxisAudit(
		method="mean_axis",
		input_lines=len(lines),
		sample_points=count,
		reversed_lines=sum(reversed_flags),
		min_length_m=min(lengths),
		max_length_m=max(lengths),
		length_ratio_min_max=min(lengths)/max(lengths),
		max_correspondence_spread_m=max(spreads),
		mean_correspondence_spread_m=sum(spreads)/len(spreads),
	)
