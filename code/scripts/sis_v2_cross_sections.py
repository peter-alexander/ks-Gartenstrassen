"""Querschnittsbreiten entlang GIP-EDGE in der zugeordneten Voronoi-Fläche.

Reiner Geometriebaustein für die nachgelagerte Segmentierung (EPSG:31256).
"""
from shapely.geometry import LineString
STEP_M = 1.
WINDOW = 5
TOLERANCE = .10
MIN_GROWTH = .20
MAX_SEARCH_M = 40.


def cross_section(polygon, axis, distance):
	"""Breite ausschließlich der Voronoi-Teilfläche an der EDGE-Position."""
	pos = axis.interpolate(distance)
	before = axis.interpolate(max(0., distance - .25))
	after = axis.interpolate(min(axis.length, distance + .25))
	dx, dy = after.x - before.x, after.y - before.y
	length = (dx * dx + dy * dy) ** .5
	if length < 1e-8:
		return None
	nx, ny = -dy / length, dx / length
	extent = 100.
	probe = LineString([
		(pos.x - nx * extent, pos.y - ny * extent),
		(pos.x + nx * extent, pos.y + ny * extent),
	])
	intersection = polygon.intersection(probe)
	if intersection.is_empty:
		return None
	segments = [intersection] if intersection.geom_type == "LineString" else (
		list(intersection.geoms) if hasattr(intersection, "geoms") else [])
	segments = [seg for seg in segments if seg.geom_type == "LineString" and seg.length > .01]
	# Kein benachbarter Straßenarm: nur der Querschnitt, der die Achse schneidet.
	containing = [seg for seg in segments if seg.distance(pos) < .10]
	if len(containing) != 1:
		return None
	return containing[0].length, containing[0]


def detect(widths):
	"""Erste stabile Fünferfolge nach messbarer anfänglicher Aufweitung."""
	for i in range(1, len(widths) - WINDOW + 1):
		chunk = widths[i:i + WINDOW]
		if any(w is None or w[0] < .5 for w in chunk):
			continue
		values = [w[0] for w in chunk]
		middle = sorted(values)[WINDOW // 2]
		if max(values) - min(values) > TOLERANCE * middle:
			continue
		earlier = [w[0] for w in widths[:i] if w is not None]
		if not earlier:
			continue
		# Vom NODE aus wachsende Fläche: vorher tatsächlich schmaler.
		if min(earlier) > (1 - MIN_GROWTH) * middle:
			continue
		return i
	return None


def evaluate(axis, polygon, *, reverse=False):
	if reverse:
		axis = LineString(list(axis.coords)[::-1])
	limit = min(MAX_SEARCH_M, axis.length * .45)
	if limit < WINDOW + 2:
		return {"status": "edge_zu_kurz"}, None
	widths = [cross_section(polygon, axis, float(d)) for d in range(int(limit) + 1)]
	index = detect(widths)
	profile = [{"abstand_m": d, "breite_m": round(w[0], 3) if w else None}
		for d, w in enumerate(widths)]
	if index is None:
		return {"status": "keine_stabile_grenze", "profil": profile}, None
	width, cross = widths[index]
	return {"status": "grenze_gefunden", "distanz_m": index,
		"breite_m": round(width, 3), "profil": profile}, cross

