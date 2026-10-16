"""Reproduzierbare Offline-Diagnose einer Wiener Voronoi-GIP-Zuordnung.

Schreibt keine Partitionsergebnisse und verändert weder GIP-Index noch
Straßenraum-Cache. Das ZIP enthält metrische Original-WKB (EPSG:31256)
und ein strukturiertes Protokoll für die gezielte Fehleruntersuchung.
"""
import argparse
import json
import math
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from shapely import intersection, make_valid, union_all
from shapely.errors import GEOSException
from shapely.geometry import Polygon
from shapely.validation import explain_validity
from shapely.wkb import dumps

from scripts.analyze_gpkg import polygonal_part
from scripts.wienwide_grid import checksum, read_manifest
from scripts.wienwide_gip import connect as connect_gip
from scripts.wienwide_partition import graph_context, split_tile
from scripts.wienwide_street import load_street_tile
from shapely.geometry import box


class _Captured(Exception):
	pass


def _describe(geometry):
	if geometry is None:
		return {"status":"keine Geometrie"}
	try:
		return {
			"typ":geometry.geom_type,
			"leer":geometry.is_empty,
			"gueltig":geometry.is_valid,
			"gueltigkeitsfehler":None if geometry.is_valid
				else explain_validity(geometry),
			"flaeche_m2":geometry.area,
			"bounds_31256":list(geometry.bounds) if not geometry.is_empty else [],
		}
	except GEOSException as exc:
		return {"status":"GEOS-Ausnahme", "fehler":str(exc)}


def _record(archive, report, name, geometry):
	report[name]=_describe(geometry)
	if geometry is not None:
		archive.writestr(f"wkb/{name}.wkb",dumps(geometry))


def _attempt(archive, report, name, builder):
	try:
		value=builder()
	except (ValueError,GEOSException) as exc:
		report[name]={"status":"Berechnung fehlgeschlagen","fehler":str(exc)}
		return None
	_record(archive,report,name,value)
	return value


def capture(path, *, tile_id, gid, axis, owner, remaining, cells,
		mask, core, street_path, manifest_path):
	"""WKB-Schnappschuss genau vor der problematischen Achsenverarbeitung."""
	path=Path(path)
	if path.exists():
		raise FileExistsError(f"Diagnose-ZIP existiert bereits: {path}")
	path.parent.mkdir(parents=True,exist_ok=True)
	report={
		"schema_version":1,
		"typ":"nur-lesen-voronoi-diagnose",
		"tile_id":tile_id,
		"gip_id":str(gid),
		"crs":"EPSG:31256",
		"street_sha256":checksum(street_path),
		"manifest_sha256":checksum(manifest_path),
		"achsen_name":axis["name"],
		"fow":axis["fow"],
		"anzahl_voronoi_einzelzellen":len(cells),
		"geometrien":{},
		"einzelzellen":[],
		"vergleich":{},
	}
	geoms=report["geometrien"]
	with ZipFile(path,"x",compression=ZIP_DEFLATED,compresslevel=6) as archive:
		for name,shape in (("kern",core),("strassenmaske",mask),
				("restmaske",remaining),("voronoi_vereinigung",owner),
				("gip_achse",axis["geometry"])):
			_record(archive,geoms,name,shape)
		individual=[]
		for index,cell in enumerate(cells):
			name=f"zellen/{index:05d}"
			_record(archive,geoms,name,cell)
			overlap=_attempt(archive,geoms,
				f"einzelschnitte/{index:05d}",
				lambda cell=cell:intersection(cell,remaining))
			if overlap is not None and not overlap.is_empty:
				poly=polygonal_part(overlap)
				if poly is not None and not poly.is_empty:
					individual.append(poly)
			report["einzelzellen"].append({
				"index":index,
				"zelle_gueltig":cell.is_valid,
				"schnitt_gueltig":None if overlap is None else overlap.is_valid,
				"schnitt_flaeche_m2":None if overlap is None else overlap.area,
			})
		merged=_attempt(archive,geoms,"vereinigung_einzelschnitte",
			lambda:union_all(individual) if individual else Polygon())
		direct=_attempt(archive,geoms,"direkter_schnitt",
			lambda:intersection(owner,remaining))
		if direct is not None and not direct.is_valid:
			_attempt(archive,geoms,"direkter_schnitt_make_valid",
				lambda:polygonal_part(make_valid(direct)))
		for grid in (1e-9,1e-8,1e-7,1e-6):
			_attempt(archive,geoms,
				f"praezisionsschnitt_{grid:g}",
				lambda grid=grid:intersection(owner,remaining,grid_size=grid))
		if merged is not None and merged.is_valid:
			for name,builder in (
				("fehlend_aus_voronoi",
					lambda:owner.difference(merged).intersection(remaining)),
				("fehlend_aus_restmaske",
					lambda:remaining.difference(merged).intersection(owner)),
				("ausserhalb_voronoi",lambda:merged.difference(owner)),
				("ausserhalb_restmaske",lambda:merged.difference(remaining)),
			):
				_attempt(archive,geoms,name,builder)
			gaps=[]
			for index,cell in enumerate(cells):
				try:
					missing=cell.difference(merged).intersection(remaining)
					area=missing.area
					if area>0.01:
						gaps.append({"index":index,"fehlend_m2":area,
							"bounds_31256":list(missing.bounds)})
						_record(archive,geoms,
							f"luecken_je_zelle/{index:05d}",missing)
				except (ValueError,GEOSException) as exc:
					gaps.append({"index":index,"fehler":str(exc)})
			report["vergleich"]["fehlende_einzelzellen"]=gaps
		report["vergleich"]["anzahl_einzelschnitte"] = len(individual)
		report["vergleich"]["summe_einzelschnittflaechen_m2"] = sum(
			part.area for part in individual)
		report["vergleich"]["ueberlappung_einzelschnitte_m2"] = (
			max(0.,sum(p.area for p in individual)-merged.area)
			if merged is not None else None)
		report["vergleich"]["vollstaendigkeitsfrage"] = (
			"Wenn die Einzelzellen keinen Anteil an der Lücke haben, "
			"aber voronoi_vereinigung minus vereinigung_einzelschnitte "
			"dort Fläche zeigt, ist die Differenz bereits in der "
			"Voronoi-Vereinigung bzw. ihrer Overlay-Topologie zu suchen."
		)
		archive.writestr("diagnose.json",
			json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
	return report


def diagnose(manifest_path, gip_index, street_root, tile_id, gid, out):
	manifest,aoi=read_manifest(manifest_path)
	tile=next((row for row in manifest["tiles"]
		if row["id"]==tile_id),None)
	if tile is None:
		raise ValueError(f"Unbekannte Wiener Rasterkachel: {tile_id}")
	source=Path(street_root)/tile_id/"street.sqlite"
	core=box(*tile["bounds_31256"]).intersection(aoi)
	street=load_street_tile(source,core)
	target={"found":False,"report":None}
	with connect_gip(gip_index) as db:
		sites,axes,nodes=graph_context(
			db,tile["bounds_31256"],halo=manifest["halo_m"])
		def visit(axis,owner,remaining,cells,mask,core):
			if str(axis["id"])!=str(gid):
				return
			target["found"]=True
			target["report"]=capture(out,tile_id=tile_id,gid=gid,
				axis=axis,owner=owner,remaining=remaining,cells=cells,
				mask=mask,core=core,street_path=source,
				manifest_path=manifest_path)
			raise _Captured()
		try:
			split_tile(street,core,sites,axes,nodes,diagnostic=visit)
		except _Captured:
			pass
	if not target["found"]:
		raise ValueError(f"Kachel {tile_id}: GIP {gid} hat dort keine "
			"Voronoi-Zellen, oder ein vorheriger Fehler hat die "
			"Diagnose verhindert")
	return target["report"]


def main():
	p=argparse.ArgumentParser(description=__doc__)
	p.add_argument("--manifest",type=Path,
		default=Path("data/processed/wienweit/wien/raster.json"))
	p.add_argument("--gip-index",type=Path,
		default=Path("data/processed/wienweit/wien/gip.sqlite"))
	p.add_argument("--street-root",type=Path,
		default=Path("data/processed/wienweit/wien/strassenraum"))
	p.add_argument("--tile-id",required=True)
	p.add_argument("--gip-id",required=True)
	p.add_argument("--out",type=Path,required=True)
	args=p.parse_args()
	try:
		report=diagnose(args.manifest,args.gip_index,args.street_root,
			args.tile_id,args.gip_id,args.out)
	except (OSError,ValueError,GEOSException) as exc:
		p.exit(1,f"Fehler: {exc}\n")
	geometry=report["geometrien"]
	summary={
		"tile_id":report["tile_id"],
		"gip_id":report["gip_id"],
		"voronoi_einzelzellen":report["anzahl_voronoi_einzelzellen"],
		"restmaske_m2":geometry["restmaske"].get("flaeche_m2"),
		"voronoi_vereinigung_m2":geometry["voronoi_vereinigung"].get(
			"flaeche_m2"),
		"direkter_schnitt":geometry["direkter_schnitt"],
		"vereinigung_einzelschnitte":geometry["vereinigung_einzelschnitte"],
		"fehlend_aus_voronoi_m2":geometry.get(
			"fehlend_aus_voronoi",{}).get("flaeche_m2"),
		"fehlend_aus_restmaske_m2":geometry.get(
			"fehlend_aus_restmaske",{}).get("flaeche_m2"),
		"auffaellige_einzelzellen":report["vergleich"].get(
			"fehlende_einzelzellen",[])[:10],
		"diagnose_zip":str(args.out),
	}
	print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=="__main__":
	main()
