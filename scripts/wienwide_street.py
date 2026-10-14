"""Stadtweite Straßenraum-Vorstufe: lokale FMZK+Kataster je Kachel -> WKB.

Die *bestehende* Straßenraumklassifikation wird unverändert verwendet.
Anders als das Test-GeoJSON wird die Berechnungsmaske unmittelbar
in EPSG:31256 als WKB in einer kleinen SQLite-Kacheldatei gespeichert.
Keine erneute WGS84-Rückprojektion. Mehrere FMZK/Kataster-Kacheln
bleiben unabhängig; Kernflächen sind durch den AOI-Plan disjunkt.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from time import perf_counter

from pyproj import Transformer
from shapely import union_all
from shapely.geometry import box
from shapely.wkb import dumps,loads

from scripts.export_fmzk_strassenraum import (
	classify_fmzk, read_kataster_masks,
)
from scripts.fmzk_source import load_polygons
from scripts.wienwide_grid import read_manifest, checksum

TO_LONLAT=Transformer.from_crs("EPSG:31256","EPSG:4326",
	always_xy=True).transform


def load_street_tile(path, core):
	"""Metrisches WKB, genau der eigene Kachel-Kern, ohne GeoJSON-Rundweg."""
	path=Path(path)
	if not path.is_file():
		raise FileNotFoundError(f"Straßenraum-Kachel fehlt: {path}")
	from urllib.parse import quote
	with sqlite3.connect("file:"+quote(str(path.resolve()),safe="/")+"?mode=ro",uri=True) as conn:
		data=dict(conn.execute("SELECT key,value FROM metadata"))
		if data.get("schema_version")!="1" or data.get("crs")!="EPSG:31256":
			raise ValueError(f"Nicht unterstützte Straßenraumkachel {path}")
		row=conn.execute("SELECT geom FROM street").fetchone()
		if row is None:
			raise ValueError(f"Straßenraum-Maske leer: {path}")
		geom=loads(row[0])
		if not geom.is_valid:
			raise ValueError(f"Straßenraum-Geometrie ungültig: {path}")
		if geom.difference(core).area>.01:
			raise ValueError(f"Straßenraum-Kachel liegt außerhalb ihrer Kernkachel: {path}")
		return geom


def save_street_tile(path, street, metadata):
	path=Path(path)
	if path.exists():
		raise FileExistsError(f"Straßenraum-Kachel existiert: {path}")
	if street.is_empty or not street.is_valid or street.area<=0:
		raise ValueError("Leere/ungültige Straßenmaske – keine scheinbar komplette Kachel")
	path.parent.mkdir(parents=True,exist_ok=True)
	temp=path.with_suffix(".sqlite.tmp")
	if temp.exists():
		raise FileExistsError(f"Temporäre Straßenraum-Kachel existiert: {temp}")
	try:
		with sqlite3.connect(temp) as db:
			db.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
			db.execute("CREATE TABLE street(geom BLOB NOT NULL)")
			db.execute("INSERT INTO street(geom) VALUES (?)",(dumps(street),))
			for key,value in metadata.items():
				db.execute("INSERT INTO metadata VALUES (?,?)",(key,
					json.dumps(value,ensure_ascii=False) if not isinstance(value,str) else value))
		temp.replace(path)
	except BaseException:
		temp.unlink(missing_ok=True)
		raise
	return path


def build_tile(tile, aoi, *, root, out, halo, report=None):
	"""Nur vorhandene lokale, geprüfte FMZK- und Kataster-Dateien lesen."""
	root,out=Path(root),Path(out)
	fmzk=root/tile["id"]/"fmzk.gpkg"
	kataster=root/tile["id"]/"kataster"
	if not fmzk.is_file():
		raise FileNotFoundError(f"FMZK-Kachel fehlt: {fmzk}")
	features,manifest,clip,repairs=load_polygons(fmzk)
	core=box(*tile["bounds_31256"]).intersection(aoi)
	# Die geometrische Klassifikation findet mit HALO statt;
	# Schnitt erst NACH Klassifikation, um Randeffekte zu mindern.
	if not clip.covers(core):
		raise ValueError(f"{tile['id']}: FMZK deckt Arbeitskern nicht ab")
	if not clip.covers(core.buffer(min(halo,20))):
		raise ValueError(f"{tile['id']}: FMZK-Halo unvollständig; "
			"größeren Ausschnitt extrahieren")
	street,other,mask_stats=read_kataster_masks(kataster,clip,manifest)
	classified=classify_fmzk(features,street,other,minimum_share=.95)
	selected=[geom for target,_props,geom in classified
		if target=="strassenraum" and geom.intersects(core)]
	if not selected:
		raise ValueError(f"{tile['id']}: keine FMZK-Straßenraumflächen im Kern")
	geometry=union_all(selected).intersection(core)
	if geometry.is_empty or not geometry.is_valid or geometry.area<=0:
		raise ValueError(f"{tile['id']}: Straßenraum-Geometrie ungültig")
	path=out/tile["id"]/"street.sqlite"
	statistics={
		"schema_version":"1","crs":"EPSG:31256",
		"tile_id":tile["id"],"aoi_area_m2":core.area,
		"strassenraum_m2":geometry.area,
		"halo_m":halo,"fmzk_sha256":checksum(fmzk),
		"kataster_bericht_sha256":checksum(kataster/"kataster_bericht.json"),
		"flaechen_fmzk":len(features),"reparaturen_fmzk":len(repairs),
		"zuordnung_anzahl":dict(Counter(x[0] for x in classified)),
		"kataster_status":mask_stats,
		"beschreibung":"Metrische V0-Basis: FMZK-Kern + nfl 95/65; "
			"95%-Regel unverändert; ohne amtliche Widmungsprüfung",
	}
	save_street_tile(path,geometry,statistics)
	if report is not None:
		report.append({"tile":tile["id"],"file":str(path),"area_m2":geometry.area})
	return statistics


def prefetch_tile(tile, *, manifest, aoi, root, source, cache, offline=False,
	max_tiles=120, max_parcels=600):
	"""Bereits vorhandenen Original-GPKG-Zuschnitt und BEV-Tiles holen.

	Vorsicht: derselbe lokale Test-Algorithmus. Überschreiben verboten,
	fehlende BEV-Daten/zu große Ausschnitte führen zum Abbruch.
	"""
	from shapely.ops import transform
	from scripts.extract_fmzk import extract
	from scripts.analyze_kataster import run as analyze_kataster
	root=Path(root)
	dest=root/tile["id"]
	fmzk=dest/"fmzk.gpkg"
	kataster=dest/"kataster"
	core=box(*tile["bounds_31256"]).intersection(aoi)
	bounds=transform(TO_LONLAT,core.buffer(manifest["halo_m"]).segmentize(5)).bounds
	bbox=tuple(float(v) for v in bounds)
	# Neues Wien-Raster: hier gilt nicht das kleine bbox-Limit
	# des Testgebiets-Parsers. Sicherheitsgrenze kommt aus der
	# metrischen Kachelgröße und dem Halo des geprüften Manifests.
	w,s,ea,n=bbox
	if not (15.5<w<ea<17.5 and 47.5<s<n<49.0):
		raise ValueError(f"{tile['id']}: ungültige Wien-BBOX")
	if core.buffer(manifest["halo_m"]).area > 30_000_000:
		raise ValueError(f"{tile['id']}: FMZK-Kachel zu groß")
	if not fmzk.exists():
		extract(source,fmzk,bbox)
	# Mit Cache und ausdrücklich gesetzten Kachel-/Grundstückslimits
	# keine unbeschränkten Abrufe.
	if not (kataster/"kataster_bericht.json").exists():
		analyze_kataster(fmzk,kataster,cache,offline=offline,
			max_tiles=max_tiles,max_parcels=max_parcels)
	return {"tile":tile["id"],"fmzk":str(fmzk),"kataster":str(kataster)}


def run(manifest_path, input_root, output_root, *, only=None):
	manifest,aoi=read_manifest(manifest_path)
	report=[]
	selected=[t for t in manifest["tiles"] if only is None or t["id"]==only]
	if not selected:
		raise ValueError("Unbekannte Tile-ID")
	for i,tile in enumerate(selected,1):
		start=perf_counter()
		stats=build_tile(tile,aoi,root=input_root,out=output_root,
			halo=manifest["halo_m"],report=report)
		print(f"Straßenraum {i}/{len(selected)} {tile['id']}: "
			f"{stats['strassenraum_m2']:.1f} m², "
			f"{perf_counter()-start:.2f}s")
	return report


def main():
	p=argparse.ArgumentParser(description=__doc__)
	sub=p.add_subparsers(dest="action",required=True)
	for command in ("fetch-inputs","build"):
		q=sub.add_parser(command)
		q.add_argument("--manifest",type=Path,required=True)
		q.add_argument("--input-root",type=Path,required=True)
		q.add_argument("--only",help="Einzelne Tile-ID für den Bezirks-Pilot")
		if command=="fetch-inputs":
			q.add_argument("--fmzk-source",type=Path,required=True)
			q.add_argument("--kataster-cache",type=Path,
				default=Path("data/cache/kataster"))
			q.add_argument("--offline",action="store_true")
			q.add_argument("--max-tiles",type=int,default=120)
			q.add_argument("--max-parcels",type=int,default=600)
		else:
			q.add_argument("--out-root",type=Path,required=True)
	args=p.parse_args()
	try:
		if args.action=="build":
			result=run(args.manifest,args.input_root,args.out_root,only=args.only)
		else:
			manifest,aoi=read_manifest(args.manifest)
			selected=[tile for tile in manifest["tiles"]
				if args.only is None or tile["id"]==args.only]
			if not selected:
				raise ValueError("Unbekannte Tile-ID")
			result=[]
			for tile in selected:
				result.append(prefetch_tile(tile,manifest=manifest,aoi=aoi,
					root=args.input_root,source=args.fmzk_source,
					cache=args.kataster_cache,offline=args.offline,
					max_tiles=args.max_tiles,max_parcels=args.max_parcels))
		print(json.dumps({"fertige_kacheln":len(result)},ensure_ascii=False))
	except (OSError,ValueError,TypeError,KeyError,sqlite3.Error) as exc:
		p.exit(1,f"Fehler: {exc}\n")


if __name__=="__main__":
	main()
