"""Publish a complete Vienna measurement and PMTiles together.

Only source data from the given output/working directory is read.
Atomic per-file replaces, with a final SHA-256 attestation as commit marker.
An interrupted publication is NOT considered valid by cleanup.
"""
import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3

from scripts.sis_v2_pmtiles import run as make_pmtiles
from scripts.wienwide_grid import checksum

FILES = ("gip_abschnitte.geojson", "gip_abschnitte.csv",
	"bericht.json", "gartenstrassen.pmtiles")
DATA = FILES[:3]
MARKER = "freigabe.json"
MEMBERS = "gip_kanten_zuordnung.csv"


def _check_measurement(source):
	report_path = source / "bericht.json"
	if not report_path.is_file() or report_path.is_symlink():
		raise FileNotFoundError(report_path)
	report = json.loads(report_path.read_text(encoding="utf-8"))
	if not report.get("manifest_sha256") or not isinstance(report.get("gip_ids"), int):
		raise ValueError("Abschlussbericht enthält keinen gültigen Wiener Quellenbezug")
	for name, key in (("gip_abschnitte.geojson", "geojson_sha256"),
			("gip_abschnitte.csv", "csv_sha256")):
		path = source / name
		if path.is_symlink() or not path.is_file() or not path.stat().st_size:
			raise FileNotFoundError(path)
		if report.get(key) != checksum(path):
			raise ValueError(f"Messausgabe {name} weicht vom Bericht ab")
	return report


def publish(source, output, *, gip_index=None):
	source, output = Path(source), Path(output)
	if output.is_symlink() or source.is_symlink():
		raise ValueError("Symlinks sind für die Veröffentlichung nicht erlaubt")
	report = _check_measurement(source)
	output.mkdir(parents=True, exist_ok=True)
	stage = output / ".publishing"
	if stage.is_symlink():
		raise ValueError("Symlink als temporärer Ausgabeordner")
	if stage.exists():
		if not stage.is_dir():
			raise FileExistsError(stage)
		# Nur einen eigenen, unvollendeten Veröffentlichungsschritt entsorgen.
		shutil.rmtree(stage)
	stage.mkdir()
	try:
		for name in DATA:
			shutil.copyfile(source/name, stage/name)
		if report.get("gip_kantenvereinigung")=="parallel-gip-groups-v1":
			if gip_index is not None and Path(gip_index).is_file():
				with sqlite3.connect(f"file:{Path(gip_index).resolve()}?mode=ro",
						uri=True) as graph, (stage/MEMBERS).open(
						"w",newline="",encoding="utf-8") as out:
					writer=csv.writer(out)
					writer.writerow(("original_gip_id","repraesentant_gip_id",
						"rolle","original_fow","original_name"))
					writer.writerows(graph.execute(
						"SELECT original_id,representative_id,role,original_fow,"
						"original_name FROM merged_members ORDER BY original_id"))
			elif (source/MEMBERS).is_file():
				shutil.copyfile(source/MEMBERS,stage/MEMBERS)
			else:
				raise FileNotFoundError(
					"Vollständige GIP-Originalzuordnung für Freigabe fehlt")
		pm = make_pmtiles(stage/"gip_abschnitte.geojson",
			stage/"gartenstrassen.pmtiles", min_area=100)
		if pm["source_sha256"] != report["geojson_sha256"]:
			raise ValueError("PMTiles und GeoJSON widersprechen sich")
		to_publish = (*FILES, *((MEMBERS,) if (stage/MEMBERS).exists() else ()))
		hashes = {name:checksum(stage/name) for name in to_publish}
		release = {
			"schema":"gartenstrassen-wien-output-v1",
			"created_utc":datetime.now(timezone.utc).isoformat(),
			"manifest_sha256":report["manifest_sha256"],
			"gip_ids":report["gip_ids"],
			"pmtiles_features":pm["gip_ids"],
			"publication_fow":pm["allowed_fow"],
			"min_area_m2":100,
			"files_sha256":hashes,
		}
		(stage/MARKER).write_text(
			json.dumps(release,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
		# Der Freigabemarker muss zuletzt erscheinen. Jeder Fehler davor
		# verhindert, dass cleanup einen unvollständigen Stand akzeptiert.
		(output/MARKER).unlink(missing_ok=True)
		for name in to_publish:
			if (output/name).is_symlink():
				raise ValueError(f"Ausgabeziel ist ein Symlink: {name}")
			os.replace(stage/name,output/name)
		os.replace(stage/MARKER,output/MARKER)
		print(f"Wien-Ausgabe: GeoJSON, CSV, PMTiles und Bericht in {output}",
			flush=True)
		return release
	finally:
		if stage.is_dir() and not stage.is_symlink():
			shutil.rmtree(stage)


def main():
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("--source",required=True,type=Path)
	p.add_argument("--out",required=True,type=Path)
	p.add_argument("--gip-index",type=Path,
		help="Vereinigter GIP-Graph für komplette Original-ID-Referenz")
	a = p.parse_args()
	print(json.dumps(publish(a.source,a.out,gip_index=a.gip_index),ensure_ascii=False,indent=2))


if __name__ == "__main__":
	main()
