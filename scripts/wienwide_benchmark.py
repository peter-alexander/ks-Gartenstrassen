"""Reproduzierbarer Vorab- und Bezirks-Benchmark der Wien-Kachelpipeline.

Ermittelt KEINE unbekannten Laufzeiten: protokolliert nur tatsächlich
von wienwide_partition erfasste Dauer je Kachel und getrennte
Quellbereitschaft. Kein vollständiger Wien-Lauf wird behauptet.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3

from scripts.wienwide_grid import read_manifest, checksum
from scripts.wienwide_partition import report_results
from scripts.wienwide_gip import connect as connect_gip, REPORT as GIP_REPORT


def benchmark(manifest_path, *, inputs, fragments, street_root, gip_index,
	partition_db=None):
	manifest,_aoi=read_manifest(manifest_path)
	inputs,fragments,street_root=(Path(x) for x in
		(inputs,fragments,street_root))
	gip_index=Path(gip_index)
	rows=[]
	for tile in manifest["tiles"]:
		folder=inputs/tile["id"]
		gip=fragments/tile["id"]
		out=street_root/tile["id"]
		row={"id":tile["id"],"core_area_m2":tile["aoi_core_m2"],
			"fmzk_vorhanden":(folder/"fmzk.gpkg").is_file(),
			"kataster_bericht_vorhanden":(folder/"kataster"/"kataster_bericht.json").is_file(),
			"gip_bericht_vorhanden":(gip/GIP_REPORT).is_file(),
			"street_sqlite_vorhanden":(out/"street.sqlite").is_file()}
		rows.append(row)
	ready={name:sum(1 for t in rows if t[name])
		for name in ("fmzk_vorhanden","kataster_bericht_vorhanden",
			"gip_bericht_vorhanden","street_sqlite_vorhanden")}
	report={
		"schema_version":1,"erstellt_utc":datetime.now(timezone.utc).isoformat(),
		"manifest_sha256":checksum(manifest_path),
		"anzahl_kacheln":len(rows),"aoi_km2":manifest["aoi_area_m2"]/1e6,
		"tile_size_m":manifest["tile_size_m"],"halo_m":manifest["halo_m"],
		"quellabdeckung":ready,
		"fehlende_kacheln":{name:[row["id"] for row in rows if not row[name]]
			for name in ready},
		"gip_katalog":None,
		"partition":None,
		"hinweis":"Zeiten umfassen nur die Voronoi-Partitionierung und "
			"das Laden ihrer lokalen Kacheln. FMZK-, Kataster-, WFS- "
			"und Kronenverarbeitungszeiten sind NICHT enthalten.",
	}
	if gip_index.is_file():
		with connect_gip(gip_index) as db:
			meta=dict((row["key"],json.loads(row["value"]))
				for row in db.execute("SELECT key,value FROM meta"))
		if meta.get("manifest_sha256")!=report["manifest_sha256"]:
			raise ValueError("GIP-Index gehört zu anderer AOI")
		report["gip_katalog"]={k:meta[k] for k in
			("achsen","knoten","voronoi_sites","tile_count",
			 "duplikate_zusammengefuehrt") if k in meta}
	if partition_db and Path(partition_db).is_file():
		with sqlite3.connect(partition_db) as db:
			stats=db.execute("SELECT id,area,assigned,unresolved,elapsed_s,stats_json FROM tiles").fetchall()
			per_tile=[{
				"id":gid,"strassenraum_m2":area,
				"zugeordnet_m2":assigned,"ungeklaert_m2":unresolved,
				"partition_s":seconds,**{
					"voronoi_sites":json.loads(details).get("sites",0),
					"kreuzungsknoten":json.loads(details).get("knoten",0)}}
				for gid,area,assigned,unresolved,seconds,details in stats]
			complete=len(per_tile)==len(rows) and (
				{item["id"] for item in per_tile}=={r["id"] for r in rows})
			if complete:
				full=report_results(db,manifest)
			else:
				full={"status":"PARTIELL – KEINE WIENWEITEN SUMMEN"}
		timing=sorted(t["partition_s"] for t in per_tile)
		report["partition"]={
			"status":"vollständig" if complete else "partiell",
			"kacheln":len(per_tile),
			"gesamt_s":sum(timing),
			"median_s":timing[len(timing)//2] if timing else None,
			"max_s":max(timing) if timing else None,
			"gesamtbilanz":full,
			"kachelwerte":per_tile,
		}
	return report


def main():
	p=argparse.ArgumentParser(description=__doc__)
	p.add_argument("--manifest",type=Path,required=True)
	p.add_argument("--inputs",type=Path,required=True)
	p.add_argument("--gip-fragments",type=Path,required=True)
	p.add_argument("--street-root",type=Path,required=True)
	p.add_argument("--gip-index",type=Path,required=True)
	p.add_argument("--partition-db",type=Path)
	p.add_argument("--out",type=Path,required=True)
	args=p.parse_args()
	try:
		result=benchmark(args.manifest,inputs=args.inputs,
			fragments=args.gip_fragments,street_root=args.street_root,
			gip_index=args.gip_index,partition_db=args.partition_db)
		if args.out.exists():
			raise FileExistsError(f"Benchmark existiert bereits: {args.out}")
		args.out.parent.mkdir(parents=True,exist_ok=True)
		args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",
			encoding="utf-8")
		print(f"Benchmark: {result['anzahl_kacheln']} Kacheln; "
			f"Quelle/Partielle Ergebnisse im Bericht: {args.out}")
	except (ValueError,TypeError,OSError,sqlite3.Error) as exc:
		p.exit(1,f"Fehler: {exc}\n")


if __name__=="__main__":
	main()
