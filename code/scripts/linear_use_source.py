"""GeoPackage LINEAR_USE readers shared by the original-geometry importer."""
import sqlite3
from pathlib import Path
from urllib.parse import quote

from pyproj import CRS
from shapely.wkb import loads

BASE_TYPE=1

def _readonly(path):
	path=Path(path).resolve()
	if not path.is_file():
		raise FileNotFoundError(path)
	return sqlite3.connect(
		"file:"+quote(str(path),safe="/")+"?mode=ro&immutable=1",uri=True)


def _gpkg_wkb(blob):
	if blob is None:
		raise ValueError("LINEAR_USE-Geometrie fehlt")
	data=bytes(blob)
	if len(data)<8 or data[:2]!=b"GP":
		raise ValueError("Ungültiger GeoPackage-Geometrieheader")
	flags=data[3]
	envelope=(flags>>1)&7
	if envelope>4:
		raise ValueError("Unbekannter GeoPackage-Envelope")
	offset=8+(0,32,48,48,64)[envelope]
	if len(data)<=offset:
		raise ValueError("GeoPackage-Geometrie ist abgeschnitten")
	return loads(data[offset:])


def _source_geometry_info(db):
	row=db.execute("""
		SELECT column_name,geometry_type_name,srs_id
		FROM gpkg_geometry_columns
		WHERE table_name='LINEAR_USE'
	""").fetchone()
	if row is None:
		raise ValueError("GeoPackage enthält keinen registrierten LINEAR_USE-Layer")
	column,geometry_type,srs_id=row
	if str(geometry_type).upper() not in ("LINESTRING","GEOMETRY"):
		raise ValueError(
			f"LINEAR_USE: unerwarteter registrierter Geometrietyp {geometry_type}")
	srs=db.execute("""
		SELECT organization,organization_coordsys_id
		FROM gpkg_spatial_ref_sys WHERE srs_id=?
	""",(srs_id,)).fetchone()
	if srs is None:
		raise ValueError(f"LINEAR_USE: unbekanntes srs_id {srs_id}")
	organization,code=srs
	try:
		crs=CRS.from_user_input(f"{organization}:{code}")
	except Exception as exc:
		raise ValueError(
			f"LINEAR_USE: CRS {organization}:{code} nicht lesbar") from exc
	return str(column),crs


def _columns(db):
	return {row[1] for row in db.execute("PRAGMA table_info('LINEAR_USE')")}


def _require_columns(db):
	required={
		"object_id","edge_id","edge_percentage_from","edge_percentage_to",
		"base_type","length_m","feature_name",
	}
	missing=required-_columns(db)
	if missing:
		raise ValueError(
			"LINEAR_USE: Pflichtspalten fehlen: "+", ".join(sorted(missing)))


def _pk_column(db):
	for row in db.execute("PRAGMA table_info('LINEAR_USE')"):
		if row[5]:
			return row[1]
	raise ValueError("LINEAR_USE: Primärschlüssel für räumlichen Index fehlt")


def _source_rows(db,geom_column,source_aoi_bounds):
	pk=_pk_column(db)
	rtree=f"rtree_LINEAR_USE_{geom_column}"
	has_rtree=db.execute(
		"SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
		(rtree,)).fetchone() is not None
	if has_rtree:
		minx,miny,maxx,maxy=source_aoi_bounds
		query=f"""
			SELECT l.object_id,l.edge_id,l.edge_percentage_from,
				l.edge_percentage_to,l.base_type,l.length_m,l.feature_name,
				l."{geom_column}"
			FROM LINEAR_USE l
			JOIN "{rtree}" r ON r.id=l."{pk}"
			WHERE l.base_type=?
				AND r.maxx>=? AND r.minx<=?
				AND r.maxy>=? AND r.miny<=?
			ORDER BY l.edge_id,l.object_id
		"""
		return db.execute(query,(BASE_TYPE,minx,maxx,miny,maxy)),True
	query=f"""
		SELECT object_id,edge_id,edge_percentage_from,edge_percentage_to,
			base_type,length_m,feature_name,"{geom_column}"
		FROM LINEAR_USE
		WHERE base_type=?
		ORDER BY edge_id,object_id
	"""
	return db.execute(query,(BASE_TYPE,)),False


