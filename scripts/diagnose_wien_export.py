"""Schreibgeschützte WKB-Diagnose fehlgeschlagener Wien-GIP-WGS84-Exporte.

Erfasst die exakt im Export benutzten EPSG:31256-Kachelfragmente,
deren Union, die unveränderte WGS84-Projektion und beide
make_valid-Kontrollschritte. Auch zusätzliche/fehlende Flächen
und die Geometrie am gemeldeten Fehlerort werden gespeichert.

Keine Publikationsfreigabe, keine Reparatur an Quelldateien.
"""
import argparse
from contextlib import closing
from hashlib import sha256
import json
import math
from pathlib import Path
import sqlite3
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZipFile

from pyproj import Transformer
from shapely import make_valid, union_all
from shapely.geometry import box
from shapely.ops import transform
from shapely.validation import explain_validity

from scripts.analyze_gpkg import decode_gpkg_geometry, polygonal_part
from scripts.wienwide_result_export import METRIC, WGS84

DEFAULT_GPKG=Path("data/processed/wienweit/wien/begruenung_grm/gip_abschnitte_begruenung.gpkg")
DEFAULT_OUT=Path("data/processed/wienweit/wien/diagnose-export-wgs84.zip")


def _describe(geometry):
	if geometry is None:
		return {"status":"nicht verfügbar"}
	try:
		return {
			"typ":geometry.geom_type,
			"leer":geometry.is_empty,
			"gueltig":geometry.is_valid,
			"gueltigkeitsfehler":None if geometry.is_valid
				else explain_validity(geometry),
			"flaeche_in_crs_einheiten":geometry.area,
			"grenzlaenge_in_crs_einheiten":geometry.boundary.length,
			"bounds":list(geometry.bounds) if not geometry.is_empty else [],
		}
	except Exception as exc:
		return {"status":"Beschreibung fehlgeschlagen","fehler":str(exc)}


def _record(archive, shapes, folder, name, geometry):
	shapes[name]=_describe(geometry)
	if geometry is not None:
		archive.writestr(
			f"{folder}/{name}.wkb",geometry.wkb)
	return geometry


def _try(archive, shapes, folder, name, builder):
	try:
		result=builder()
	except Exception as exc:
		shapes[name]={"status":"Berechnung fehlgeschlagen","fehler":str(exc)}
		return None
	return _record(archive,shapes,folder,name,result)


def _read_gip(gpkg,gid):
	path=Path(gpkg)
	if not path.is_file():
		raise FileNotFoundError(f"Begrünungs-GeoPackage fehlt: {path}")
	uri="file:"+quote(str(path.resolve()),safe="/")+"?mode=ro"
	result=[]
	with closing(sqlite3.connect(uri,uri=True)) as db:
		for fid,blob,area in db.execute(
			"SELECT fid,geom,flaeche_m2 FROM gip_abschnitte "
			"WHERE gip_id=? ORDER BY fid",(str(gid),)):
			geom=decode_gpkg_geometry(blob,fid)
			if geom.is_empty or not geom.is_valid or geom.area<=0:
				raise ValueError(f"GIP {gid}/FID {fid}: ungültige Quelle")
			if abs(geom.area-area)>max(.01,geom.area*1e-8):
				raise ValueError(f"GIP {gid}/FID {fid}: "
					"GeoPackage- und WKB-Fläche stimmen nicht überein")
			result.append((fid,geom,area))
	if not result:
		raise ValueError(f"GIP {gid}: keine Teilflächen im GeoPackage")
	return result


def _diagnose_one(archive,gid,rows,lon,lat,radius_m):
	folder=f"gip_{gid}"
	shapes={}
	fragment_meta=[]
	parts=[]
	digest=sha256()
	for index,(fid,geom,area) in enumerate(rows):
		name=f"fragment_{index:05d}"
		_record(archive,shapes,folder,name,geom)
		digest.update(str(fid).encode("ascii"))
		digest.update(geom.wkb)
		fragment_meta.append({"fid":fid,"flaeche_m2":area,
			"wkb_sha256":sha256(geom.wkb).hexdigest()})
		parts.append(geom)
	metric=_try(archive,shapes,folder,"00_original_metric_union",
		lambda:union_all(parts))
	if metric is None or metric.is_empty or not metric.is_valid:
		raise ValueError(f"GIP {gid}: ursprüngliche Union nicht gültig")
	wgs=_try(archive,shapes,folder,"01_wgs84_unveraendert",
		lambda:transform(WGS84,metric))
	if wgs is None:
		raise ValueError(f"GIP {gid}: direkte WGS84-Projektion gescheitert")
	wgs_fixed_all=_try(archive,shapes,folder,"02_wgs84_make_valid_voll",
		lambda:make_valid(wgs))
	wgs_fixed=_try(archive,shapes,folder,"03_wgs84_repariert_polygonal",
		lambda:polygonal_part(wgs_fixed_all)
			if wgs_fixed_all is not None else None)
	back=_try(archive,shapes,folder,"04_rueckprojektion_unveraendert",
		lambda:transform(METRIC,wgs_fixed)
			if wgs_fixed is not None else None)
	back_fixed_all=_try(archive,shapes,folder,"05_rueck_make_valid_voll",
		lambda:make_valid(back) if back is not None else None)
	back_fixed=_try(archive,shapes,folder,"06_rueck_repariert_polygonal",
		lambda:polygonal_part(back_fixed_all)
			if back_fixed_all is not None else None)
	# Zusätzlicher Normal-Roundtrip: zur Trennung von
	# Projektionsdrift und durch make_valid entstehender Abweichung.
	normal_back=_try(archive,shapes,folder,"07_normaler_roundtrip",
		lambda:transform(METRIC,wgs))
	measures={}
	if back_fixed is not None and not back_fixed.is_empty and back_fixed.is_valid:
		extra=_try(archive,shapes,folder,"08_zusaetzliche_metric",
			lambda:back_fixed.difference(metric))
		missing=_try(archive,shapes,folder,"09_fehlende_metric",
			lambda:metric.difference(back_fixed))
		try:
			measures["grenzverschiebung_hausdorff_m"]=(
				metric.boundary.hausdorff_distance(back_fixed.boundary))
			measures["flaechenaenderung_m2"]=back_fixed.area-metric.area
			measures["zusaetzlich_m2"]=extra.area if extra is not None else None
			measures["fehlend_m2"]=missing.area if missing is not None else None
		except Exception as exc:
			measures["messfehler"]=str(exc)
		if lon is not None and lat is not None:
			x,y=METRIC(lon,lat)
			local=box(x-radius_m,y-radius_m,x+radius_m,y+radius_m)
			for name,geometry in (
				("10_fehlstelle_original_31256",metric),
				("11_fehlstelle_rueckprojektion_31256",back_fixed),
				("12_fehlstelle_zusaetzlich_31256",extra),
				("13_fehlstelle_fehlend_31256",missing),
			):
				if geometry is not None:
					_try(archive,shapes,folder,name,
						lambda geometry=geometry:geometry.intersection(local))
			measures["diagnosezentrum_31256"]=[x,y]
			measures["ausschnitt_radius_m"]=radius_m
	report={
		"gip_id":str(gid),
		"crs_metrisch":"EPSG:31256",
		"crs_export":"EPSG:4326",
		"fragmente":fragment_meta,
		"fragmente_sha256":digest.hexdigest(),
		"anzahl_fragmente":len(rows),
		"urspruengliche_summe_m2":sum(r[2] for r in rows),
		"messwerte":measures,
		"geometrien":shapes,
		"hinweis":"Alle WKB-Dateien sind schreibgeschützte Belege. "
			"Geometrie-Namen mit _metric oder _31256 sind EPSG:31256; "
			"WGS84-Namen sind EPSG:4326. Polygonale make_valid-Auswahl "
			"verwirft nichtpolygonale Linien/Punkte nur für den Vergleich, "
			"nicht für die Originaldaten.",
	}
	return report


def diagnose(gpkg,out,gip_ids,*,lon=None,lat=None,radius_m=3):
	"""Diagnose exakt benannter GIP-IDs ohne Seiteneffekt auf GPkg."""
	if (lon is None)!=(lat is None):
		raise ValueError("Länge und Breite nur gemeinsam angeben")
	if radius_m<=0 or not math.isfinite(radius_m):
		raise ValueError("Diagnoseradius muss positiv und endlich sein")
	if not gip_ids or len(set(map(str,gip_ids)))!=len(gip_ids):
		raise ValueError("Mindestens eine eindeutige GIP-ID benötigt")
	out=Path(out)
	if out.exists():
		raise FileExistsError(f"Diagnose-ZIP existiert bereits: {out}")
	# Erst alle Ausgangsgeometrien lesen und validieren, dann
	# überhaupt eine Ausgabedatei anlegen.
	all_rows={str(gid):_read_gip(gpkg,gid) for gid in gip_ids}
	out.parent.mkdir(parents=True,exist_ok=True)
	report={
		"schema_version":1,
		"art":"read-only WGS84-Export-Fehlerdiagnose",
		"quelle":str(gpkg),
		"gip_ids":list(all_rows),
		"ausgaben":{},
	}
	try:
		with ZipFile(out,"x",compression=ZIP_DEFLATED,compresslevel=6) as archive:
			for gid,rows in all_rows.items():
				report["ausgaben"][gid]=_diagnose_one(archive,gid,rows,
					lon,lat,radius_m)
			archive.writestr("diagnose.json",
				json.dumps(report,ensure_ascii=False,indent=2,
					allow_nan=False)+"\n")
	except BaseException:
		out.unlink(missing_ok=True)
		raise
	return report


def main():
	p=argparse.ArgumentParser(description=__doc__)
	p.add_argument("--gpkg",type=Path,default=DEFAULT_GPKG)
	p.add_argument("--out",type=Path,default=DEFAULT_OUT)
	p.add_argument("--gip-id",action="append",dest="gip_ids")
	p.add_argument("--lon",type=float,default=None)
	p.add_argument("--lat",type=float,default=None)
	p.add_argument("--radius-m",type=float,default=3)
	args=p.parse_args()
	if args.gip_ids is None:
		args.gip_ids=["10023323"]
	try:
		report=diagnose(args.gpkg,args.out,args.gip_ids,
			lon=args.lon,lat=args.lat,radius_m=args.radius_m)
	except (OSError,ValueError,sqlite3.Error) as exc:
		p.exit(1,f"Fehler: {exc}\n")
	for gid,result in report["ausgaben"].items():
		print(json.dumps({
			"gip_id":gid,
			"fragmente":result["anzahl_fragmente"],
			"metrik":result["messwerte"],
			"wgs84_gueltig":result["geometrien"]
				["01_wgs84_unveraendert"].get("gueltig"),
			"wgs84_fehler":result["geometrien"]
				["01_wgs84_unveraendert"].get("gueltigkeitsfehler"),
			"rueckprojektion_gueltig":result["geometrien"]
				["04_rueckprojektion_unveraendert"].get("gueltig"),
			"diagnose_zip":str(args.out),
		},ensure_ascii=False,indent=2))


if __name__=="__main__":
	main()
