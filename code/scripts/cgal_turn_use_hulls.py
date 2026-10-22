"""Historic GIP2 NODE/TURN_USE convex-junction hull rule, before CGAL dissolve.

Reimplemented directly from the former scripts/sis_gip2.py (commit
07374b16c192): group TURN_USE geometry by via_node_id=NODE.object_id;
collect ALL TURN_USE line vertices, regardless of base_type; build a
MultiPoint convex_hull for each NODE; accept Polygon with area > 0.
No arbitrary junction buffers, no base_type filtering, no invented hull
for collinear / missing TURN_USE geometry.

The historical SIS pipeline intersected those hulls with its SIS mask
before subtracting them from the street partition. In the current
pre-SIS pipeline we clip hulls only to the existing Vienna AOI, then
subtract them from each native CGAL Face *before* edge_id union.
"""
from collections import Counter
import math
from pathlib import Path
import sqlite3
from urllib.parse import quote

from pyproj import Transformer
from shapely.geometry import MultiPoint
from shapely.ops import transform
from shapely.wkb import loads

TO_METRIC=Transformer.from_crs("EPSG:4326","EPSG:31256",
	always_xy=True).transform
TO_WGS=Transformer.from_crs("EPSG:31256","EPSG:4326",
	always_xy=True).transform

# The original local GIP2 pipeline queried TURN_USE within the AOI
# envelope buffered by (the default SIS halo 75m + 35m).
TURN_SEARCH_MARGIN_M=110


def gpkg_geom(blob):
	"""Exact GeoPackage header/GeoPackage WKB extraction from the V2 adapter."""
	if blob is None:
		return None
	data=bytes(blob)
	if len(data)<9 or data[:2]!=b"GP":
		raise ValueError("Ungültiger GeoPackage-Geometrieheader")
	flags=data[3]
	envelope=(flags>>1)&7
	if envelope>4:
		raise ValueError("Unbekannter GeoPackage-Envelope")
	offset=8+(0,32,48,48,64)[envelope]
	if len(data)<=offset:
		raise ValueError("Abgeschnittener GeoPackage-Geometrieheader")
	return loads(data[offset:])


def _spatial(src,table,bounds):
	x0,y0,x1,y1=bounds
	return src.execute(f'''SELECT t.* FROM "{table}" t
		JOIN "rtree_{table}_geom" r ON r.id=t.fid
		WHERE r.maxx>=? AND r.minx<=? AND r.maxy>=? AND r.miny<=?''',
		(x0,x1,y0,y1))


def load_turn_use_hulls(source,aoi,*,progress=None):
	"""Return actual V2 convex junction hulls clipped to the Vienna AOI.

	A NODE from within the AOI envelope belongs to a group identified by
	NODE.object_id. Every TURN_USE line from the original spatial search
	window with matching via_node_id contributes ALL its coordinates.
	Do not mask by base_type; no synthetic point buffers.
	"""
	source=Path(source)
	if not source.is_file() or not source.stat().st_size:
		raise FileNotFoundError(f"GIP-Netzwerk-GeoPackage fehlt: {source}")
	if aoi.is_empty or not aoi.is_valid or aoi.area<=0:
		raise ValueError("TURN_USE-Ausschluss benötigt gültige Wiener AOI")
	# Densify rectangle before inverse projection so curved projected
	# boundaries are covered by the RTree query.
	node_bbox=transform(TO_WGS,aoi.envelope.segmentize(10)).bounds
	turn_bbox=transform(TO_WGS,
		aoi.envelope.buffer(TURN_SEARCH_MARGIN_M).segmentize(10)).bounds
	stats=Counter()
	node_groups={}
	with sqlite3.connect("file:"+quote(str(source.resolve()),safe="/")+"?mode=ro",
			uri=True) as src:
		src.row_factory=sqlite3.Row
		for table in ("NODE","TURN_USE"):
			if not src.execute("SELECT 1 FROM gpkg_contents WHERE table_name=?",
					(table,)).fetchone():
				raise ValueError(f"GIP2-GeoPackage: Layer {table} fehlt")
			if not src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
					("rtree_"+table+"_geom",)).fetchone():
				raise ValueError(f"GIP2-GeoPackage: RTree für {table} fehlt")
		for row in _spatial(src,"NODE",node_bbox):
			geom=gpkg_geom(row["geom"])
			if geom is None or geom.is_empty:
				continue
			if geom.geom_type!="Point":
				raise ValueError("GIP2 NODE enthält keinen Punkt")
			metric=transform(TO_METRIC,geom)
			if not aoi.envelope.covers(metric):
				continue
			node_id=str(row["object_id"])
			if not node_id or node_id in node_groups:
				raise ValueError(f"Doppelte oder ungültige NODE-ID: {node_id}")
			node_groups[node_id]={"points":[],"turn_count":0}
			stats["nodes_in_aoi_envelope"]+=1
		if not node_groups:
			raise ValueError("GIP2: keine NODE-Punkte im Wiener Suchbereich")
		for row in _spatial(src,"TURN_USE",turn_bbox):
			node_id=row["via_node_id"]
			if node_id is None:
				continue
			group=node_groups.get(str(node_id))
			if group is None:
				continue
			geom=gpkg_geom(row["geom"])
			if geom is None or geom.is_empty:
				continue
			if geom.geom_type not in ("LineString","MultiLineString"):
				raise ValueError(f"TURN_USE {row['object_id']}: keine Linie")
			metric=transform(TO_METRIC,geom)
			group["turn_count"]+=1
			stats["turn_use_lines_used"]+=1
			for line in (metric.geoms if metric.geom_type=="MultiLineString"
					else (metric,)):
				group["points"].extend(line.coords)
				stats["turn_use_vertices_used"]+=len(line.coords)
			if progress and stats["turn_use_lines_used"]%20000==0:
				progress(f"TURN_USE: {stats['turn_use_lines_used']:,} "
					"Linien für NODE-Hüllen verarbeitet")
	hulls=[]
	for node_id,group in node_groups.items():
		coords=group["points"]
		hull=MultiPoint(coords).convex_hull if coords else None
		if hull is None or hull.geom_type!="Polygon" or hull.area<=0:
			stats["nodes_without_polygonal_hull"]+=1
			continue
		if not hull.is_valid:
			raise ValueError(f"NODE {node_id}: ungültige konvexe TURN_USE-Hülle")
		stats["original_polygonal_junction_hulls"]+=1
		stats["original_hull_area_sum_m2"]+=hull.area
		# Historical method: mask by the study area before subtraction.
		clipped=hull.intersection(aoi)
		if clipped.is_empty or clipped.area==0:
			stats["junction_hulls_outside_aoi"]+=1
			continue
		if not clipped.is_valid or clipped.geom_type not in ("Polygon","MultiPolygon"):
			raise ValueError(f"NODE {node_id}: TURN_USE-Hülle nach AOI-Schnitt ungültig")
		hulls.append((node_id,clipped))
		stats["hulls_intersecting_aoi"]+=1
		stats["clipped_hull_area_sum_m2"]+=clipped.area
	stats["historic_rule"]="all_TURN_USE_per_via_node_id_convex_hull_no_base_type_filter"
	stats["search_margin_m"]=TURN_SEARCH_MARGIN_M
	stats["crs"]="EPSG:31256"
	return hulls,dict(stats)
