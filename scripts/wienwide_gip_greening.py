"""Begrünung und GRM2023-Baumschicht pro GIP-V0-Abschnitt (EPSG:31256).

Boden: FMZK F_KLASSE 58/69 (je Tile metrisch vereinigt).
Baumschicht: optional vollständige geprüfte wienwide_grm2023-Masken.
Einheit der Auswertung: vorhandene (Tile, GIP-ID) Teilfläche, FOW=3.
Jede Quote nutzt NUR die tatsächlich dieser GIP-ID zugeteilte Fläche.
Nicht zugeordnete, Sonderachsen- und Knotenbereiche bleiben im QA
GeoPackage erhalten, fließen NICHT in Abschnittskennzahlen ein.

Ergebnis: QA-GPKG-Kopie mit zusätzlichen Kennzahlenspalten, CSV je
globaler GIP-ID, JSON-Provenienz. Nichts an Ursprungsdateien ändern.
"""
import argparse
from collections import defaultdict
from contextlib import closing
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3

from shapely import union_all
from shapely.geometry import box
from shapely.wkb import loads

from scripts.fmzk_source import FMZK_GROUND_GREEN_CODES,load_polygons
from scripts.wienwide_grid import read_manifest,checksum
from scripts.export_fmzk_strassenraum import STREET_CLASSIFICATION_VERSION
from scripts.wienwide_partition import report_results
from scripts.wienwide_grm2023 import read_mask as read_grm
from scripts.wienwide_gip import connect as connect_gip

CODES=tuple(sorted(FMZK_GROUND_GREEN_CODES))
SCHEMA=1
CSV_COLUMNS=("gip_id","strassenname","fow","abschnitt_flaeche_m2",
	"boden_m2","boden_pct","boden_58_m2","boden_69_m2",
	"boden_klassen_ueberlagerung_m2","grm_kronen_m2",
	"grm_kronen_pct","kachelteile")


def _read_meta(db,table):
	return dict(db.execute(f"SELECT key,value FROM {table}"))


def _fmzk_mask(features,core):
	"""Zwei getrennte FMZK-Quellklassen; Union verhindert Doppelzählung."""
	per_code={}
	for code in CODES:
		parts=[geom.intersection(core) for _fid,category,_label,geom in features
			if category==code and geom.intersects(core)]
		parts=[part for part in parts if not part.is_empty and part.area>0]
		per_code[code]=union_all(parts) if parts else None
		if per_code[code] is not None and not per_code[code].is_valid:
			raise ValueError(f"FMZK-Grünmaske {code} ist ungültig")
	all_parts=[m for m in per_code.values() if m is not None]
	total=union_all(all_parts) if all_parts else None
	if total is not None and not total.is_valid:
		raise ValueError("FMZK-Grünvereinigung ungültig")
	return total,per_code


def _coverage(geom,mask):
	if mask is None or mask.is_empty:
		return 0.
	return geom.intersection(mask).area


def _tile_parts(db,tile_id):
	return db.execute("""SELECT gip_id,area,geom FROM parts
		WHERE tile_id=? AND kind='abschnitt' ORDER BY gip_id""",
		(tile_id,))


def _compute(manifest_path,gip_index,street_root,input_root,
		partition_path,qa_path,grm_root=None):
	manifest,aoi=read_manifest(manifest_path)
	manifest_sha=checksum(manifest_path)
	gip_sha=checksum(gip_index)
	street_root=Path(street_root)
	input_root=Path(input_root)
	partition_path=Path(partition_path)
	qa_path=Path(qa_path)
	grm_root=Path(grm_root) if grm_root is not None else None
	if not qa_path.is_file():
		raise FileNotFoundError(f"QA-GeoPackage fehlt: {qa_path}")
	with closing(sqlite3.connect(f"file:{partition_path.resolve()}?mode=ro",
		uri=True)) as source, connect_gip(gip_index) as gip:
		config=_read_meta(source,"config")
		expected={"manifest_sha256":manifest_sha,"gip_sha256":gip_sha,
			"schema_version":"1"}
		if config!=expected:
			raise ValueError("Partition und Manifest/GIP-Index passen nicht zusammen")
		balance=report_results(source,manifest)
		gip.row_factory=sqlite3.Row
		axes={r["gip"]:(r["name"],r["fow"])
			for r in gip.execute("SELECT gip,name,fow FROM axes")}
		with closing(sqlite3.connect(f"file:{qa_path.resolve()}?mode=ro",
			uri=True)) as qa:
			raw=_read_meta(qa,"qa_provenienz")
			qmeta={k:json.loads(v) for k,v in raw.items()}
			if (qmeta.get("manifest_sha256")!=manifest_sha or
				qmeta.get("gip_sha256")!=gip_sha or
				qmeta.get("partition_sha256")!=checksum(partition_path) or
				qmeta.get("kacheln")!=len(manifest["tiles"])):
				raise ValueError("QA-GeoPackage gehört zu anderen Quelldaten")
			qa_ids={(row[0],row[1]):row[2] for row in qa.execute(
				"SELECT kachel_id,gip_id,flaeche_m2 FROM gip_abschnitte")}
			qa_streets=qmeta.get("street_sha256") or {}
		per_tile={}
		per_gid=defaultdict(lambda:{"area":0.,"boden":0.,"58":0.,
			"69":0.,"overlap":0.,"crown":0.,"parts":0})
		source_hashes={}
		crown_hashes={}
		seen=set()
		for idx,tile in enumerate(manifest["tiles"],1):
			tid=tile["id"]
			core=box(*tile["bounds_31256"]).intersection(aoi)
			street=street_root/tid/"street.sqlite"
			street_hash=checksum(street)
			row=source.execute("SELECT street_sha256,area FROM tiles WHERE id=?",
				(tid,)).fetchone()
			if (row is None or row[0]!=street_hash
				or qa_streets.get(tid)!=street_hash):
				raise ValueError(f"{tid}: Straßenraum/Partition/QA-Quellen abweichend")
			fmzk=input_root/tid/"fmzk.gpkg"
			fmzk_sha=checksum(fmzk)
			with closing(sqlite3.connect(f"file:{street.resolve()}?mode=ro",
				uri=True)) as street_db:
				metadata=_read_meta(street_db,"metadata")
				if metadata.get("strassenraum_regel_version")!=STREET_CLASSIFICATION_VERSION:
					raise ValueError(f"{tid}: Straßenraum aus veralteter FMZK-Regelversion")
				if metadata.get("fmzk_sha256")!=fmzk_sha:
					raise ValueError(f"{tid}: FMZK seit Straßenraumberechnung verändert")
			features,extraction,clip,_repairs=load_polygons(fmzk)
			if not clip.covers(core):
				raise ValueError(f"{tid}: FMZK-Grünquelle deckt den Kachelkern nicht")
			green,per_code=_fmzk_mask(features,core)
			crown=None
			if grm_root is not None:
				crown,crown_meta=read_grm(grm_root,tile,
					manifest=manifest_path,aoi=aoi)
				crown_hashes[tid]=crown_meta
			count=0
			for gid,area,wkb in _tile_parts(source,tid):
				axis=axes.get(gid)
				if axis is None or axis[1]!=3:
					raise ValueError(f"{tid}/{gid}: GIP-Achse fehlt/FOW ungleich 3")
				part=loads(wkb)
				if part.is_empty or not part.is_valid or part.area<=0:
					raise ValueError(f"{tid}/{gid}: ungültiges Abschnittspolygon")
				if (abs(part.area-area)>max(.01,part.area*1e-8)
					or part.difference(core).area>.01):
					raise ValueError(f"{tid}/{gid}: Geometrie/Fläche inkonsistent")
				if (tid,gid) not in qa_ids:
					raise ValueError(f"{tid}/{gid}: fehlt im QA-GeoPackage")
				if abs(qa_ids[(tid,gid)]-area)>max(.01,area*1e-8):
					raise ValueError(f"{tid}/{gid}: QA-Fläche weicht ab")
				area_58=_coverage(part,per_code.get(58))
				area_69=_coverage(part,per_code.get(69))
				boden=_coverage(part,green)
				overlap=max(0.,area_58+area_69-boden)
				grm=_coverage(part,crown) if grm_root is not None else None
				if (boden>area+.01 or area_58>area+.01 or area_69>area+.01
					or (grm is not None and grm>area+.01)):
					raise ValueError(f"{tid}/{gid}: Grün/Kronenfläche über Abschnitt")
				result={"gip_id":gid,"kachel_id":tid,"area":area,
					"boden":boden,"58":area_58,"69":area_69,
					"overlap":overlap,"crown":grm}
				per_tile[(tid,gid)]=result
				tot=per_gid[gid]
				for key,value in (("area",area),("boden",boden),
					("58",area_58),("69",area_69),
					("overlap",overlap),("crown",grm or 0.)):
					tot[key]+=value
				tot["parts"]+=1
				count+=1
				seen.add((tid,gid))
			source_hashes[tid]=fmzk_sha
			print(f"Begrünung {idx}/{len(manifest['tiles'])} {tid}: "
				f"{count} Abschnittsfragmente")
		if set(qa_ids)!=seen:
			raise ValueError("QA-GeoPackage enthält unerwartete GIP-Abschnitte")
		if len(per_gid)!=balance["geometrisch_eindeutige_gip_ids"]:
			raise ValueError("Anzahl der GIP-IDs stimmt nicht mit Partitionsbericht")
		if abs(sum(t["area"] for t in per_gid.values())-
			balance["abschnitte_m2"])>max(.05,balance["abschnitte_m2"]*1e-6):
			raise ValueError("Gesamtfläche der GIP-Abschnitte weicht ab")
		rows=[]
		for gid,stats in sorted(per_gid.items()):
			name,fow=axes[gid]
			area=stats["area"]
			rows.append({
				"gip_id":gid,"strassenname":name,"fow":fow,
				"abschnitt_flaeche_m2":area,
				"boden_m2":stats["boden"],
				"boden_pct":100*stats["boden"]/area,
				"boden_58_m2":stats["58"],
				"boden_69_m2":stats["69"],
				"boden_klassen_ueberlagerung_m2":stats["overlap"],
				"grm_kronen_m2":stats["crown"] if grm_root is not None else None,
				"grm_kronen_pct":100*stats["crown"]/area if grm_root is not None else None,
				"kachelteile":stats["parts"],
			})
		summary={
			"schema_version":SCHEMA,
			"stand_utc":datetime.now(timezone.utc).isoformat(),
			"crs":"EPSG:31256",
			"status":"vorläufige abschnittsbezogene V0-Bodenbegrünung "+
				("und GRM2023-WMS-Baumschicht" if grm_root is not None
					else "(Baumschicht noch NICHT berechnet)"),
			"gip_ids":len(per_gid),
			"abschnittsfragmente":len(per_tile),
			"strassenraum_m2":balance["strassenraum_m2"],
			"ausgewertete_abschnittsflaeche_m2":balance["abschnitte_m2"],
			"nicht_in_abschnittsquoten_m2":balance["ungeklaert_m2"],
			"nicht_in_abschnittsquoten_gruppen_m2":balance["klassengruppen"],
			"ausgewertet_pct_vom_strassenraum":
				100*balance["abschnitte_m2"]/balance["strassenraum_m2"],
			"boden_m2":sum(t["boden"] for t in per_gid.values()),
			"boden_pct_abschnittsflaeche":100*sum(
				t["boden"] for t in per_gid.values())/balance["abschnitte_m2"],
			"grm_kronen_m2":sum(t["crown"] for t in per_gid.values())
				if grm_root is not None else None,
			"grm_kronen_pct_abschnittsflaeche":100*sum(
				t["crown"] for t in per_gid.values())/balance["abschnitte_m2"]
				if grm_root is not None else None,
			"gruenklassen_fmzk":list(CODES),
			"eingaben":{"manifest_sha256":manifest_sha,"gip_sha256":gip_sha,
				"partition_sha256":checksum(partition_path),
				"qa_sha256":checksum(qa_path),
				"fmzk_sha256":source_hashes,
				"grm_masks":crown_hashes if grm_root is not None else None},
			"hinweise":[
				"Alle Quoten verwenden nur FOW=3 zugeordnete GIP-Abschnittsfläche.",
				"FOW!=3-Sonderachsen, Knotenbereiche und Restflächen bleiben in "+
				"der Flächenbilanz, aber nicht im Abschnittsnenner.",
				"Bodenbegrünung = geometrische Vereinigung von FMZK 58/69 "+
				"innerhalb der Abschnittspolygone; 58 und 69 können überlappen.",
				"GRM2023 ist die gerenderte WMS-Baumschicht, kein "+
				"amtliches Rohpolygon; Boden- und Kronenprozente NICHT addieren.",
				"Fehlende GRM-Quelle wird NULL (unbekannt), niemals Null-Prozent."
			]}
		return summary,rows,per_tile


def _write_spatial(qa,output,per_tile,report):
	shutil.copy2(qa,output)
	with sqlite3.connect(output) as db:
		existing={row[1] for row in db.execute(
			'PRAGMA table_info("gip_abschnitte")')}
		for key in ("boden_m2","boden_pct","boden_58_m2","boden_69_m2",
				"boden_klassen_ueberlagerung_m2","grm_kronen_m2","grm_kronen_pct"):
			if key in existing:
				raise ValueError(f"Spalte bereits im QA-GeoPackage: {key}")
			db.execute(f'ALTER TABLE gip_abschnitte ADD COLUMN "{key}" REAL')
		# GeoPackage-RTree-Trigger erwarten ST_IsEmpty/MinX aus GDAL.
		# Python-SQLite besitzt diese Funktionen nicht. Da wir NUR
		# Spaltenwerte, niemals Geometrie oder FID, aktualisieren,
		# Trigger für die Dauer des Attribut-Joins sicher aussetzen.
		# Alle originalen SQL-Definitionen unmittelbar wiederherstellen.
		triggers=db.execute("""SELECT name,sql FROM sqlite_master
			WHERE type='trigger' AND name LIKE 'rtree_gip_abschnitte_geom_%'
			ORDER BY name""").fetchall()
		if len(triggers)!=6:
			raise ValueError("GeoPackage-RTree-Trigger der Abschnitte unvollständig")
		for name,_sql in triggers:
			db.execute('DROP TRIGGER "'+name+'"')
		count=0
		for fid,tid,gid,area in db.execute(
			"SELECT fid,kachel_id,gip_id,flaeche_m2 FROM gip_abschnitte").fetchall():
			m=per_tile.get((tid,gid))
			if m is None or abs(area-m["area"])>.01:
				raise ValueError(f"{tid}/{gid}: Abschnitt fehlt/abweichende Fläche")
			db.execute("""UPDATE gip_abschnitte SET
				boden_m2=?,boden_pct=?,boden_58_m2=?,boden_69_m2=?,
				boden_klassen_ueberlagerung_m2=?,grm_kronen_m2=?,
				grm_kronen_pct=? WHERE fid=?""",
				(m["boden"],100*m["boden"]/area,m["58"],m["69"],
					m["overlap"],m["crown"],
					100*m["crown"]/area if m["crown"] is not None else None,
					fid))
			count+=1
		if count!=len(per_tile):
			raise ValueError("Geopackage: unvollständige Abschnittsaktualisierung")
		for _name,sql in triggers:
			db.execute(sql)
		if db.execute("SELECT COUNT(*) FROM rtree_gip_abschnitte_geom"
			).fetchone()[0]!=count:
			raise ValueError("RTree-Index der Abschnittsgeometrien ist unvollständig")
		db.execute("INSERT INTO qa_provenienz VALUES (?,?)",
			("gip_begruenung_v1",json.dumps(report,ensure_ascii=False)))
		if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
			raise ValueError("Integritätsprüfung des Begrünungs-GPKG fehlgeschlagen")


def run(manifest,gip_index,street_root,input_root,partition_db,qa_gpkg,
		out_dir,grm_root=None):
	out_dir=Path(out_dir)
	if out_dir.exists():
		raise FileExistsError(f"Ausgabeordner existiert bereits: {out_dir}")
	temp=out_dir.with_name(out_dir.name+".tmp")
	if temp.exists():
		raise FileExistsError(f"Temporärer Ausgabeordner existiert: {temp}")
	summary,rows,per_tile=_compute(manifest,gip_index,street_root,input_root,
		partition_db,qa_gpkg,grm_root)
	temp.mkdir(parents=True)
	try:
		with (temp/"gip_abschnitte_begruenung.csv").open(
			"w",newline="",encoding="utf-8") as handle:
			writer=csv.DictWriter(handle,fieldnames=CSV_COLUMNS)
			writer.writeheader()
			writer.writerows(rows)
		(temp/"begruenung_bericht.json").write_text(
			json.dumps(summary,ensure_ascii=False,indent=2)+"\n",
			encoding="utf-8")
		_write_spatial(qa_gpkg,temp/"gip_abschnitte_begruenung.gpkg",
			per_tile,summary)
		temp.replace(out_dir)
	except BaseException:
		shutil.rmtree(temp)
		raise
	print(json.dumps({"ausgabe":str(out_dir),
		"gip_ids":summary["gip_ids"],
		"abschnittsflaeche_m2":summary["ausgewertete_abschnittsflaeche_m2"],
		"boden_m2":summary["boden_m2"],
		"boden_pct":summary["boden_pct_abschnittsflaeche"],
		"grm_kronen_m2":summary["grm_kronen_m2"],
		"grm_kronen_pct":summary["grm_kronen_pct_abschnittsflaeche"]},
		ensure_ascii=False,indent=2))
	return summary


def main():
	p=argparse.ArgumentParser(description=__doc__)
	p.add_argument("--manifest",type=Path,required=True)
	p.add_argument("--gip-index",type=Path,required=True)
	p.add_argument("--street-root",type=Path,required=True)
	p.add_argument("--input-root",type=Path,required=True)
	p.add_argument("--partition-db",type=Path,required=True)
	p.add_argument("--qa-gpkg",type=Path,required=True)
	p.add_argument("--grm-root",type=Path,
		help="Nur bei vollständig vorhandenen GRM2023-Masken angeben")
	p.add_argument("--out-dir",type=Path,required=True)
	args=p.parse_args()
	try:
		run(args.manifest,args.gip_index,args.street_root,args.input_root,
			args.partition_db,args.qa_gpkg,args.out_dir,args.grm_root)
	except (OSError,ValueError,KeyError,TypeError,sqlite3.Error) as exc:
		p.exit(1,f"Fehler: {exc}\n")


if __name__=="__main__":
	main()
