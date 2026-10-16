"""Read-only full Vienna publication preflight: find ALL export geometry failures.

Uses exactly the export validation and WGS84 conversion code, but does
not write the GeoJSON. The full CSV/GPKG and source geometry remain untouched.
Optionally includes evidence WKB for the first N failing GIP IDs in a ZIP.
"""
import argparse
from contextlib import closing
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import sqlite3
from urllib.parse import quote
from zipfile import ZipFile,ZIP_DEFLATED

from shapely import union_all
from shapely.ops import transform

from scripts.analyze_gpkg import decode_gpkg_geometry
from scripts.diagnose_wien_export import _diagnose_one,_read_gip
from scripts.wienwide_result_export import (
	WGS84,_check_totals,_read_gp_meta,_rows,_verified_wgs84,
)
from scripts.wienwide_grid import checksum

DEFAULT_ROOT=Path("data/processed/wienweit/wien")
DEFAULT_CSV=DEFAULT_ROOT/"begruenung_grm/gip_abschnitte_begruenung.csv"
DEFAULT_GPKG=DEFAULT_ROOT/"begruenung_grm/gip_abschnitte_begruenung.gpkg"
DEFAULT_REPORT=DEFAULT_ROOT/"wgs84_export_vorpruefung.json"
DEFAULT_ZIP=DEFAULT_ROOT/"wgs84_export_fehlstellen.zip"


def _inspect_group(gid,fragments,reported_area):
	if not fragments:
		raise ValueError(f"{gid}: keine Polygonfragmente")
	parts=[]
	for fid,blob,part_area in fragments:
		geom=decode_gpkg_geometry(blob,fid)
		if geom.is_empty or not geom.is_valid or geom.area<=0:
			raise ValueError(f"{gid}/{fid}: ungültige Polygongeometrie")
		if abs(geom.area-part_area)>max(.01,part_area*1e-8):
			raise ValueError(f"{gid}/{fid}: Geometrie/Fläche inkonsistent")
		parts.append(geom)
	merged=union_all(parts)
	if (merged.is_empty or not merged.is_valid or
		abs(merged.area-reported_area)>max(.05,reported_area*1e-6)):
		raise ValueError(f"{gid}: Vereinigung verändert die Abschnittsfläche")
	repairs=[]
	verified=_verified_wgs84(merged,transform(WGS84,merged),gid,repairs)
	if verified.is_empty or not verified.is_valid:
		raise ValueError(f"{gid}: Ergebnis der Exportprüfung ungültig")
	return repairs


def scan(csv_path=DEFAULT_CSV,gpkg_path=DEFAULT_GPKG,
		report_path=DEFAULT_REPORT,zip_path=DEFAULT_ZIP,
		*,min_area_m2=100,max_diagnostics=25):
	"""Checks every eligible GIP; collects all failures instead of stopping."""
	csv_path,gpkg_path,report_path=map(Path,
		(csv_path,gpkg_path,report_path))
	zip_path=Path(zip_path) if zip_path is not None else None
	if not math.isfinite(min_area_m2) or min_area_m2<0:
		raise ValueError("Mindestfläche muss endlich und nichtnegativ sein")
	if not isinstance(max_diagnostics,int) or max_diagnostics<0:
		raise ValueError("Maximale Diagnosezahl muss nichtnegativ sein")
	if report_path.exists() or report_path.with_suffix(
			report_path.suffix+".tmp").exists():
		raise FileExistsError(f"Vorprüfungsbericht existiert bereits: {report_path}")
	if zip_path is not None and (zip_path.exists() or zip_path.with_suffix(
			zip_path.suffix+".tmp").exists()):
		raise FileExistsError(f"Diagnose-ZIP existiert bereits: {zip_path}")
	if zip_path is not None and zip_path==report_path:
		raise ValueError("Bericht und ZIP müssen unterschiedliche Pfade haben")
	items=_rows(csv_path)
	selected={gid:r for gid,r in items.items()
		if float(r["abschnitt_flaeche_m2"])>=min_area_m2}
	if not selected:
		raise ValueError("Keine GIP-ID erfüllt die Mindestfläche")
	failed=[]
	accepted_repairs=[]
	processed=0
	last_gid=None
	fragments=[]
	seen=set()

	def finish(gid,parts):
		nonlocal processed
		if gid is None or gid not in selected:
			return
		processed+=1
		seen.add(gid)
		area=float(selected[gid]["abschnitt_flaeche_m2"])
		try:
			corrections=_inspect_group(gid,parts,area)
			if corrections:
				accepted_repairs.extend(corrections)
		except Exception as exc:
			# We collect errors as evidence, never accept them.
			failed.append({"gip_id":gid,"fehler":str(exc),
				"fragmentanzahl":len(parts),"abschnittsflaeche_m2":area})
		if processed%1000==0:
			print(f"WGS84-Vorprüfung: {processed}/{len(selected)} GIP-IDs, "
				f"{len(failed)} Fehler")

	uri="file:"+quote(str(gpkg_path.resolve()),safe="/")+"?mode=ro"
	with closing(sqlite3.connect(uri,uri=True)) as db:
		meta=_read_gp_meta(db)
		_check_totals(db,items,meta)
		for fid,gid,blob,part_area in db.execute(
			"SELECT fid,gip_id,geom,flaeche_m2 FROM gip_abschnitte "
			"ORDER BY gip_id,fid"):
			if gid!=last_gid:
				finish(last_gid,fragments)
				fragments=[]
				last_gid=gid
			if gid in selected:
				fragments.append((fid,blob,part_area))
		finish(last_gid,fragments)
	if processed!=len(selected) or seen!=set(selected):
		raise ValueError("Vorprüfung hat nicht alle GIP-IDs verarbeitet")

	report={
		"schema_version":1,
		"zeitpunkt_utc":datetime.now(timezone.utc).isoformat(),
		"status":"READ-ONLY – keine Freigabe/Änderung der Publikation",
		"min_area_m2":min_area_m2,
		"source_csv_sha256":checksum(csv_path),
		"source_gpkg_sha256":checksum(gpkg_path),
		"gip_ids_gesamt":len(items),
		"gip_ids_im_export":len(selected),
		"gip_ids_geprueft":processed,
		"gip_ids_fehlgeschlagen":len(failed),
		"gip_ids_bestanden":processed-len(failed),
		"wgs84_korrekturereignisse_bestanden":len(accepted_repairs),
		"fehler":failed,
		"bestandene_korrekturen":accepted_repairs,
		"max_diagnostics":max_diagnostics,
	}
	# The failed GIP list is complete. ZIP WKB evidence can be capped
	# to keep it small and manageable for transfer.
	evidence=failed[:max_diagnostics]
	zip_temp=(zip_path.with_suffix(zip_path.suffix+".tmp")
		if zip_path is not None and evidence else None)
	report["diagnosezip_erfasst"]=len(evidence) if zip_temp else 0
	report["diagnosezip_nicht_erfasst"]=(
		len(failed)-len(evidence) if zip_temp else len(failed))
	report["diagnosezip"]=str(zip_path) if zip_temp else None
	report_temp=report_path.with_suffix(report_path.suffix+".tmp")
	report_path.parent.mkdir(parents=True,exist_ok=True)
	if zip_temp is not None:
		zip_path.parent.mkdir(parents=True,exist_ok=True)
	try:
		if zip_temp is not None:
			with ZipFile(zip_temp,"x",compression=ZIP_DEFLATED,
					compresslevel=6) as archive:
				records={}
				for entry in evidence:
					gid=entry["gip_id"]
					try:
						records[gid]=_diagnose_one(archive,gid,
							_read_gip(gpkg_path,gid),None,None,3)
					except Exception as exc:
						records[gid]={"diagnose_fehler":str(exc)}
				archive.writestr("diagnose.json",json.dumps({
					"schema_version":1,
					"art":"read-only WGS84 export preflight findings",
					"ids":list(records),
					"ausgaben":records,
				},ensure_ascii=False,indent=2,allow_nan=False)+"\n")
		report_temp.write_text(json.dumps(report,ensure_ascii=False,
			indent=2,allow_nan=False)+"\n",encoding="utf-8")
		if zip_temp is not None:
			zip_temp.replace(zip_path)
		report_temp.replace(report_path)
	except BaseException:
		report_temp.unlink(missing_ok=True)
		if zip_temp is not None:
			zip_temp.unlink(missing_ok=True)
		raise
	return report


def main():
	p=argparse.ArgumentParser(description=__doc__)
	p.add_argument("--csv",type=Path,default=DEFAULT_CSV)
	p.add_argument("--gpkg",type=Path,default=DEFAULT_GPKG)
	p.add_argument("--report",type=Path,default=DEFAULT_REPORT)
	p.add_argument("--zip",type=Path,default=DEFAULT_ZIP)
	p.add_argument("--min-area-m2",type=float,default=100)
	p.add_argument("--max-diagnostics",type=int,default=25)
	args=p.parse_args()
	try:
		report=scan(args.csv,args.gpkg,args.report,args.zip,
			min_area_m2=args.min_area_m2,
			max_diagnostics=args.max_diagnostics)
	except (OSError,ValueError,TypeError,sqlite3.Error) as exc:
		p.exit(1,f"Fehler: {exc}\n")
	print(json.dumps({
		"gepruefte_gip_ids":report["gip_ids_geprueft"],
		"fehlgeschlagen":report["gip_ids_fehlgeschlagen"],
		"bestanden":report["gip_ids_bestanden"],
		"bestandene_korrekturen":report[
			"wgs84_korrekturereignisse_bestanden"],
		"fehlstellen_ids":[x["gip_id"] for x in report["fehler"]],
		"bericht":str(args.report),
		"diagnosezip":report["diagnosezip"],
		"diagnosezip_erfasst":report["diagnosezip_erfasst"],
	},ensure_ascii=False,indent=2))


if __name__=="__main__":
	main()
