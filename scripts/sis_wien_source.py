"""Räumliche Abfragen auf den deduplizierten Wiener SIS-Featureindex."""
from shapely import union_all
from shapely.wkb import loads


def geometries(db, core, *, belags=None):
	x0,y0,x1,y1 = core.bounds
	rows = db.execute("""
		SELECT f.belag,f.geom FROM features f
		JOIN feature_index r ON r.id=f.id
		WHERE r.maxx>=? AND r.minx<=? AND r.maxy>=? AND r.miny<=?
	""", (x0,x1,y0,y1))
	for belag,blob in rows:
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
