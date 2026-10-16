"""Baut aus dem geprüften Wiener Gartenstraßen-Export direkt PMTiles v3.

NUR Publikationsdaten: Originalmessungen, GeoPackage und GeoJSON
werden weder neu berechnet noch verändert. Der Tippecanoe-MVT-Layer
ist eine zoomabhängige DARSTELLUNG und keine metrische Analysequelle.
"""
import argparse
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import shutil
import subprocess

from shapely.geometry import shape

from scripts.wienwide_gip_greening import CSV_COLUMNS
from scripts.wienwide_grid import checksum

DEFAULT_SOURCE=Path(
	"data/processed/wienweit/wien/veroeffentlichung_100m2")
LAYER="gartenstrassen_wien"
MIN_ZOOM=8
MAX_ZOOM=17

_FLOATS={
	"abschnitt_flaeche_m2","boden_m2","boden_pct",
	"boden_58_m2","boden_69_m2",
	"boden_klassen_ueberlagerung_m2",
	"grm_kronen_m2","grm_kronen_pct",
}
_INTS={"fow","kachelteile"}
_PREFIX='{"type":"FeatureCollection","features":['


def _expected_csv(path,min_area):
	with path.open("r",newline="",encoding="utf-8") as source:
		reader=csv.DictReader(source)
		if reader.fieldnames!=list(CSV_COLUMNS):
			raise ValueError("Export-CSV hat ein unerwartetes Schema")
		rows={}
		for row in reader:
			gid=row["gip_id"]
			if (not gid or not gid.isdecimal() or gid in rows
				or int(row["fow"])!=3):
				raise ValueError(f"Export-CSV: ungültige GIP-ID/FOW: {gid}")
			area=float(row["abschnitt_flaeche_m2"])
			if not math.isfinite(area) or area<min_area:
				raise ValueError(f"Export-CSV: Fläche kleiner Grenzwert: {gid}")
			rows[gid]=row
	return rows


def _features(path):
	"""Streaming-Parser für das vom eigenen Export erzeugte FeatureCollection.

	Verarbeitet jeweils ein einzelnes Feature: kein json.load des
	gesamten, potenziell sehr großen Wiener GeoJSON erforderlich.
	"""
	decoder=json.JSONDecoder()
	with path.open("r",encoding="utf-8") as source:
		if source.read(len(_PREFIX))!=_PREFIX:
			raise ValueError("GeoJSON: unerwartete FeatureCollection-Struktur")
		buffer=""
		position=0
		def take():
			nonlocal buffer,position
			while True:
				if position>=len(buffer):
					buffer=source.read(1024*1024)
					position=0
					if not buffer:
						raise ValueError("GeoJSON unerwartet beendet")
				if not buffer[position].isspace():
					char=buffer[position]
					position+=1
					return char
				position+=1
		while True:
			# Zu Beginn kommt sofort das erste Feature oder ']'.
			next_char=take()
			if next_char=="]":
				break
			if next_char!="{":
				raise ValueError("GeoJSON: Feature-Objekt erwartet")
			position-=1
			while True:
				try:
					feature,end=decoder.raw_decode(buffer,position)
					break
				except json.JSONDecodeError as exc:
					more=source.read(1024*1024)
					if not more:
						raise ValueError("GeoJSON: unvollständiges/ungültiges "
							"Feature-JSON") from exc
					buffer+=more
			position=end
			yield feature
			delimiter=take()
			if delimiter=="]":
				break
			if delimiter!=",":
				raise ValueError("GeoJSON: fehlendes Komma/Array-Ende")
		if take()!="}":
			raise ValueError("GeoJSON: FeatureCollection nicht geschlossen")
		if buffer[position:].strip() or source.read().strip():
			raise ValueError("GeoJSON: unerwarteter Inhalt nach FeatureCollection")


def _check_properties(gid,props,row):
	if set(props)!=set(CSV_COLUMNS):
		raise ValueError(f"{gid}: GeoJSON-Attributschema abweichend")
	for key in CSV_COLUMNS:
		expected=row[key]
		value=props[key]
		if key in _INTS:
			if type(value) is not int or value!=int(expected):
				raise ValueError(f"{gid}: Attribut {key} abweichend")
		elif key in _FLOATS:
			if not expected:
				if value is not None:
					raise ValueError(f"{gid}: Attribut {key} nicht NULL")
			elif (type(value) not in (int,float)
				or not math.isfinite(value)
				or not math.isclose(float(expected),value,
					rel_tol=1e-12,abs_tol=1e-8)):
				raise ValueError(f"{gid}: Attribut {key} abweichend")
		elif value!=expected:
			raise ValueError(f"{gid}: Attribut {key} abweichend")


def validate_source(directory):
	"""Independent consistency check across export report, CSV and GeoJSON."""
	directory=Path(directory)
	csv_path=directory/"gip_abschnitte.csv"
	geojson_path=directory/"gip_abschnitte.geojson"
	report_path=directory/"export_bericht.json"
	report=json.loads(report_path.read_text(encoding="utf-8"))
	if (report.get("schema_version")!=1
		or report.get("min_area_m2")!=100
		or not isinstance(report.get("output_gip_ids"),int)
		or report["output_gip_ids"]<1
		or report.get("full_gip_ids")!=report["output_gip_ids"]+
			report.get("omitted_gip_ids",0)):
		raise ValueError("Exportbericht unvollständig oder Mindestfläche != 100 m²")
	rows=_expected_csv(csv_path,100)
	if len(rows)!=report["output_gip_ids"]:
		raise ValueError("Export-CSV-Zahl weicht vom Exportbericht ab")
	seen=set()
	for feature in _features(geojson_path):
		if not isinstance(feature,dict) or feature.get("type")!="Feature":
			raise ValueError("GeoJSON enthält keine gültigen Features")
		gid=feature.get("id")
		if not isinstance(gid,str) or gid not in rows or gid in seen:
			raise ValueError(f"GeoJSON-GIP-ID fehlt/doppelt/unbekannt: {gid}")
		props=feature.get("properties")
		if not isinstance(props,dict) or props.get("gip_id")!=gid:
			raise ValueError(f"{gid}: keine passende GIP-ID in Properties")
		_check_properties(gid,props,rows[gid])
		geometry=feature.get("geometry")
		if not isinstance(geometry,dict) or geometry.get("type") not in (
				"Polygon","MultiPolygon"):
			raise ValueError(f"{gid}: keine Polygongeometrie")
		shp=shape(geometry)
		if shp.is_empty or not shp.is_valid or shp.area<=0:
			raise ValueError(f"{gid}: GeoJSON-Geometrie ungültig")
		seen.add(gid)
	if seen!=set(rows):
		raise ValueError(f"GeoJSON unvollständig: {len(seen)}/{len(rows)} GIP-IDs")
	return {"gip_ids":len(seen),"exportbericht":report,
		"csv_sha256":checksum(csv_path),
		"geojson_sha256":checksum(geojson_path),
		"exportbericht_sha256":checksum(report_path)}


def _tippecanoe_version(binary):
	result=subprocess.run([binary,"--version"],check=True,
		capture_output=True,text=True)
	message=result.stdout+"\n"+result.stderr
	match=re.search(r"\b(?:v)?(\d+)\.(\d+)(?:\.(\d+))?\b",message)
	if not match:
		raise ValueError(f"Tippecanoe-Version nicht lesbar: {message.strip()}")
	version=tuple(map(int,match.groups(default="0")))
	if version<(2,17,0):
		raise ValueError("Tippecanoe >= 2.17 mit direktem PMTiles-Output "
			f"erforderlich; gefunden: {version}")
	return ".".join(map(str,version))


def build(source_dir=DEFAULT_SOURCE,*,tippecanoe=None,pmtiles=None,
		replace=False):
	"""Build PMTiles; --replace keeps both old files until QA succeeds.

	After validation, move the existing archive and manifest to
	*.previous.* before publishing the new pair. On publication errors,
	restore the previous pair and never delete its backup on failure.
	"""
	source_dir=Path(source_dir)
	output=source_dir/f"{LAYER}.pmtiles"
	manifest=source_dir/"pmtiles_bericht.json"
	temp=source_dir/f"{LAYER}.tmp.pmtiles"
	temp_manifest=source_dir/"pmtiles_bericht.json.tmp"
	backup_output=source_dir/f"{LAYER}.previous.pmtiles"
	backup_manifest=source_dir/"pmtiles_bericht.previous.json"
	if output.exists()!=manifest.exists():
		raise ValueError("PMTiles und Manifest müssen gemeinsam vorhanden sein")
	existing=output.exists()
	if existing and not replace:
		raise FileExistsError("PMTiles bereits vorhanden: für den gesicherten "
			"Neubau --replace angeben")
	for p in (temp,temp_manifest):
		if p.exists():
			raise FileExistsError(f"Temporäre Datei existiert bereits: {p}")
	if replace and existing:
		for p in (backup_output,backup_manifest):
			if p.exists():
				raise FileExistsError(f"Bestehende Sicherung darf nicht "
					f"überschrieben werden: {p}")
	tippecanoe=tippecanoe or shutil.which("tippecanoe")
	if tippecanoe is None:
		raise FileNotFoundError("Tippecanoe >=2.17 fehlt (felt/tippecanoe)")
	version=_tippecanoe_version(tippecanoe)
	pmtiles=pmtiles or shutil.which("pmtiles")
	source=validate_source(source_dir)
	args=[
		tippecanoe,
		"--output",str(temp),
		"--layer",LAYER,
		"--minimum-zoom",str(MIN_ZOOM),
		"--maximum-zoom",str(MAX_ZOOM),
		"--full-detail=12","--low-detail=12",
		"--simplify-only-low-zooms",
		"--no-tiny-polygon-reduction",
		"--no-feature-limit","--no-tile-size-limit",
		"--convert-stringified-ids-to-numbers",
		"--use-attribute-for-id=gip_id",
		"--name","Wien Gartenstraßen – Begrünungsanalyse",
		str(source_dir/"gip_abschnitte.geojson"),
	]
	try:
		subprocess.run(args,check=True)
		with temp.open("rb") as stream:
			header=stream.read(8)
		if (header!=b"PMTiles\x03" or temp.stat().st_size<=127):
			raise ValueError("Tippecanoe hat kein gültiges PMTiles-v3-Archiv "
				"erzeugt (Header/Länge)")
		verified=False
		if pmtiles:
			subprocess.run([pmtiles,"verify",str(temp)],check=True)
			verified=True
		result={
			"schema_version":1,
			"created_utc":datetime.now(timezone.utc).isoformat(),
			"status":"Vektor-Darstellung, keine metrische Messquelle",
			"layer":LAYER,
			"zoom_min":MIN_ZOOM,"zoom_max":MAX_ZOOM,
			"feature_ids":"gip_id als numerische MVT-Feature-ID, "
				"gip_id als Zeichenkette in Properties",
			"input_features":source["gip_ids"],
			"ersetzt_bestehendes_archiv":existing,
			"vorheriges_archiv":str(backup_output) if existing else None,
			"vorheriger_bericht":str(backup_manifest) if existing else None,
			"tippecanoe_version":version,
			"archive_bytes":temp.stat().st_size,
			"archive_sha256":checksum(temp),
			"archive_structural_verify":verified,
			"exportbericht_sha256":source["exportbericht_sha256"],
			"geojson_sha256":source["geojson_sha256"],
			"csv_sha256":source["csv_sha256"],
			"hinweis":"MVT clippt Geometrien an Kachelgrenzen und quantisiert "
				"Koordinaten je Zoomstufe. Sehr kleine Polygone können "
				"auf niedrigen Zoomstufen verschwinden. Die 24.306 "
				"GIP-IDs sind vollständige QUELL-Features, keine "
				"garantierte Anzahl dekodierter Tile-Features.",
		}
		temp_manifest.write_text(json.dumps(result,ensure_ascii=False,
			indent=2,allow_nan=False)+"\n",encoding="utf-8")
		# Beide bisherigen Ergebnisse bleiben bis zu diesem Punkt
		# unverändert. Erst nach vollständiger Validierung austauschen.
		archived_output=False
		archived_manifest=False
		new_output=False
		new_manifest=False
		try:
			if existing:
				output.replace(backup_output)
				archived_output=True
				manifest.replace(backup_manifest)
				archived_manifest=True
			temp.replace(output)
			new_output=True
			temp_manifest.replace(manifest)
			new_manifest=True
		except BaseException:
			# Veröffentlichtes neues Paar zurücknehmen und danach
			# die gesicherte Version vollständig wiederherstellen.
			if new_output:
				output.unlink(missing_ok=True)
			if new_manifest:
				manifest.unlink(missing_ok=True)
			if archived_output:
				backup_output.replace(output)
			if archived_manifest:
				backup_manifest.replace(manifest)
			raise
		return result
	except BaseException:
		temp.unlink(missing_ok=True)
		temp_manifest.unlink(missing_ok=True)
		raise


def main():
	p=argparse.ArgumentParser(description=__doc__)
	p.add_argument("--source-dir",type=Path,default=DEFAULT_SOURCE)
	p.add_argument("--tippecanoe",default=None)
	p.add_argument("--pmtiles",default=None,
		help="PMTiles-CLI für zusätzliche Archiv-Strukturprüfung")
	p.add_argument("--replace",action="store_true",
		help="PMTiles und Bericht nach erfolgreichem Neubau gesichert "
			"ersetzen; vorhandene .previous-Dateien werden nie überschrieben")
	args=p.parse_args()
	try:
		result=build(args.source_dir,tippecanoe=args.tippecanoe,
			pmtiles=args.pmtiles,replace=args.replace)
	except (OSError,ValueError,subprocess.CalledProcessError) as exc:
		p.exit(1,f"Fehler: {exc}\n")
	print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":
	main()
