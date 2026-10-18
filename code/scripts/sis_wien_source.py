"""Räumliche Abfragen auf den deduplizierten Wiener SIS-Featureindex."""
from shapely import union_all
from shapely.wkb import loads


def _candidates(db, core):
	"""Eine einzige räumlich indizierte Abfrage je Kachel."""
	x0,y0,x1,y1 = core.bounds
	return db.execute("""
		SELECT f.belag,f.geom FROM features f
		JOIN feature_index r ON r.id=f.id
		WHERE r.maxx>=? AND r.minx<=? AND r.maxy>=? AND r.miny<=?
	""", (x0,x1,y0,y1))


def geometries(db, core, *, belags=None):
	for belag,blob in _candidates(db,core):
		if belags is not None and (belag in belags) is False:
			continue
		polygon = loads(blob)
		if polygon.intersects(core):
			section = polygon.intersection(core)
			if section.area > 0:
				yield section


def mask(db, core, belags=None):
	pieces = list(geometries(db,core,belags=belags))
	return union_all(pieces) if pieces else None


def vegetation_mask(db, core, vegetation_codes):
	"""Beide Belagsklassen aus derselben RTree-Abfrage aufbauen.

	Weder ein vollständiger Scan aller SIS-Features noch eine zweite
	RTree-Abfrage sind notwendig. Die konservative Vorrangregel bleibt:
	begrünte Vereinigung minus Vereinigung aller anderen Beläge.
	"""
	green = []
	other = []
	for belag,blob in _candidates(db,core):
		polygon = loads(blob)
		if not polygon.intersects(core):
			continue
		section = polygon.intersection(core)
		if section.area <= 0:
			continue
		if belag in vegetation_codes:
			green.append(section)
		else:
			other.append(section)
	if not green:
		return None
	green_union = union_all(green)
	return green_union.difference(union_all(other)) if other else green_union
