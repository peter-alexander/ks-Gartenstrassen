"""Amtliche Bezirks-AOIs aus dem Wiener OGD-WFS, ohne manuelle BBOX.

Quelle: Stadt Wien/MA41, BEZIRKSGRENZEOGD, Lizenz CC BY 4.0.
Erzeugt einzelne Polygon-AOIs (EPSG:4326) für wienwide_grid
sowie optional die Vereinigungsfläche von Wien.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from shapely import union_all
from shapely.geometry import MultiPolygon, Polygon, mapping, shape

from scripts.geojson_crs import require_geojson_lonlat

SERVICE="https://data.wien.gv.at/daten/geo"
LAYER="ogdwien:BEZIRKSGRENZEOGD"
DATASET="https://www.data.gv.at/katalog/dataset/2ee6b8bf-6292-413c-bb8b-bd22dbb2ad4b"
MAX_BYTES=25_000_000


def source_url():
	return SERVICE+"?"+urlencode([
		("service","WFS"),("request","GetFeature"),("version","1.1.0"),
		("typeName",LAYER),("srsName","EPSG:4326"),("outputFormat","json"),
	])


def download(url=None):
	req=Request(url or source_url(),headers={
		"User-Agent":"ks-Gartenstrassen/bezirks-aoi-1.0",
		"Accept":"application/json",
	})
	with urlopen(req,timeout=60) as response:
		data=response.read(MAX_BYTES+1)
	if len(data)>MAX_BYTES:
		raise ValueError("Bezirksgrenzen-WFS überschreitet Größenlimit")
	return data


def _bez_number(properties):
	for key in ("BEZNR","BEZ","BEZ_NR","BEZIRKSNR"):
		value=properties.get(key)
		try:
			number=int(value)
		except (TypeError,ValueError):
			continue
		if 1<=number<=23:
			return number
	raise ValueError(f"Bezirksnummer fehlt/ungültig in {sorted(properties)}")


def read_boundaries(raw, *, require_complete=True):
	"""Eindeutige 1–23 Bezirke, gültige Polygone und WGS84 prüfen."""
	if not isinstance(raw,bytes) or len(raw)>MAX_BYTES:
		raise ValueError("WFS benötigt Byte-Antwort innerhalb des Größenlimits")
	try:
		data=json.loads(raw.decode("utf-8-sig"))
	except (UnicodeError,json.JSONDecodeError) as exc:
		raise ValueError("Bezirks-WFS lieferte kein GeoJSON") from exc
	if not isinstance(data,dict) or data.get("type")!="FeatureCollection":
		raise ValueError("Bezirks-WFS erwartet GeoJSON FeatureCollection")
	require_geojson_lonlat(data,label="Bezirksgrenzen")
	features=data.get("features")
	if not isinstance(features,list) or not features:
		raise ValueError("Bezirksgrenzen leer")
	for key in ("totalFeatures","numberMatched"):
		value=data.get(key)
		if value is not None and value!="unknown":
			try:
				count=int(value)
			except (ValueError,TypeError) as exc:
				raise ValueError(f"Ungültige WFS-Anzahl {key}") from exc
			if count>len(features):
				raise ValueError(f"Unvollständige Bezirks-WFS-Antwort: "
					f"{len(features)} statt {count} Features")
			if count<len(features):
				raise ValueError("Widersprüchliche WFS-Anzahl")
	by_district={}
	for index,feature in enumerate(features):
		if not isinstance(feature,dict) or feature.get("type")!="Feature":
			raise ValueError(f"Kein Bezirks-Feature bei {index}")
		props=feature.get("properties")
		if not isinstance(props,dict):
			raise ValueError(f"Bezirksattribute bei {index} fehlen")
		number=_bez_number(props)
		if number in by_district:
			raise ValueError(f"Bezirksnummer mehrfach geliefert: {number}")
		geom=shape(feature.get("geometry"))
		if not isinstance(geom,(Polygon,MultiPolygon)) or (
			geom.is_empty or not geom.is_valid or geom.area<=0):
			raise ValueError(f"Bezirk {number}: ungültiges Polygon")
		x0,y0,x1,y1=geom.bounds
		if not (15.5<x0<x1<17.5 and 47.5<y0<y1<49.0):
			raise ValueError(f"Bezirk {number}: Koordinaten nicht Wien/WGS84")
		by_district[number]={
			"geometry":geom,"name":str(props.get("NAMEK") or
				props.get("NAMEG") or props.get("BEZ_NAMEG") or ""),
			"properties":props}
	if require_complete and set(by_district)!=set(range(1,24)):
		raise ValueError(f"Bezirksgrenzen nicht vollständig: "
			f"fehlend {sorted(set(range(1,24))-set(by_district))}")
	return by_district


def create_aois(raw, out_dir, *, numbers=(9,22), whole_city=False):
	"""Alle Ausgaben erst nach vollständiger Quellenprüfung schreiben."""
	by_district=read_boundaries(raw)
	numbers=tuple(sorted(set(numbers)))
	if any(n not in by_district for n in numbers):
		raise ValueError("Unbekannter Bezirk")
	out_dir=Path(out_dir)
	files={f"bezirk_{number:02d}":out_dir/f"bezirk_{number:02d}.geojson"
		for number in numbers}
	if whole_city:
		files["wien"]=out_dir/"wien.geojson"
	cache=out_dir/"bezirksgrenzen_wfs.geojson"
	report_file=out_dir/"bezirksgrenzen_bericht.json"
	if any(p.exists() for p in [*files.values(),cache,report_file]):
		raise FileExistsError("AOI-Ausgabe bereits vorhanden – nicht überschreiben")
	city=union_all([entry["geometry"] for entry in by_district.values()])
	if whole_city and (not isinstance(city,(Polygon,MultiPolygon)) or
		city.is_empty or not city.is_valid):
		raise ValueError("Vereinigte Wiener Landesfläche ist nicht gültig")
	report={
		"schema_version":1,
		"created_utc":datetime.now(timezone.utc).isoformat(),
		"quelle":source_url(),"lizenz":"CC BY 4.0, Stadt Wien / MA41",
		"dataset":DATASET,
		"wfs_sha256":hashlib.sha256(raw).hexdigest(),
		"wfs_features":len(by_district),
		"bezirke":{str(k):{"name":v["name"]} for k,v in sorted(by_district.items())},
		"ausgaben":{k:str(path) for k,path in files.items()},
	}
	# Kleine, validierte und vollständige WFS-Antwort; lokale
	# Cache-Quelle für spätere Reproduktion unverändert speichern.
	out_dir.mkdir(parents=True,exist_ok=True)
	cache.write_bytes(raw)
	for key,path in files.items():
		if key=="wien":
			geom=city;prop={"name":"Wien","bezirk":"alle"}
		else:
			number=int(key.split("_")[1])
			geom=by_district[number]["geometry"]
			prop={"name":by_district[number]["name"],"bezirk":number}
		doc={"type":"FeatureCollection","features":[{
			"type":"Feature","properties":prop,
			"geometry":mapping(geom)}]}
		path.write_text(json.dumps(doc,ensure_ascii=False)+"\n",encoding="utf-8")
	report_file.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",
		encoding="utf-8")
	return report


def main():
	p=argparse.ArgumentParser(description=__doc__)
	p.add_argument("--out-dir",type=Path,required=True)
	p.add_argument("--source",type=Path,help="Vorher heruntergeladenes WFS-GeoJSON")
	p.add_argument("--bezirke",type=int,nargs="*",default=[9,22])
	p.add_argument("--wien",action="store_true",
		help="Zusätzlich die Vereinigungsfläche von ganz Wien exportieren")
	args=p.parse_args()
	try:
		raw=args.source.read_bytes() if args.source else download()
		report=create_aois(raw,args.out_dir,numbers=args.bezirke,
			whole_city=args.wien)
		print(json.dumps({"ausgaben":report["ausgaben"],
			"quelle_sha256":report["wfs_sha256"]},ensure_ascii=False,indent=2))
	except (OSError,ValueError,TypeError,KeyError) as exc:
		p.exit(1,f"Fehler: {exc}\n")


if __name__=="__main__":
	main()
