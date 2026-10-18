"""Delete only reproducible work/ after validating the completed Vienna output.

Default is read-only verification. --apply deletes work/ and nothing else.
Neither raw/ nor the Windows Downloads source directory is accessed for writes.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

REPO = Path(__file__).resolve().parents[2]


def checksum(path):
	h = hashlib.sha256()
	with Path(path).open("rb") as file:
		for block in iter(lambda: file.read(1024 * 1024), b""):
			h.update(block)
	return h.hexdigest()


def verify(repo):
	repo = Path(repo).resolve()
	work = repo / "work"
	out = repo / "output"
	if work.is_symlink() or out.is_symlink():
		raise ValueError("work/ und output/ dürfen keine Symlinks sein")
	if not work.is_dir():
		raise FileNotFoundError(f"Arbeitsdaten fehlen: {work}")
	files = {}
	for name in ("gip_abschnitte.geojson", "gip_abschnitte.csv",
			"bericht.json", "gartenstrassen.pmtiles"):
		file = out / name
		if file.is_symlink() or not file.is_file() or file.stat().st_size == 0:
			raise FileNotFoundError(f"Vollständige Ausgabe fehlt: {file}")
		files[name] = file
	# Der Freigabemarker wird erst nach erfolgreicher Veröffentlichung
	# aller vier Dateien geschrieben. Einzelne Restdateien zählen nicht.
	marker = out / "freigabe.json"
	if marker.is_symlink() or not marker.is_file():
		raise FileNotFoundError("Keine vollständig freigegebene Wiener Ausgabe")
	release = json.loads(marker.read_text(encoding="utf-8"))
	if release.get("schema") != "gartenstrassen-wien-output-v1":
		raise ValueError("Unbekannter Wiener Ausgabevertrag")
	for name,file in files.items():
		if release.get("files_sha256",{}).get(name) != checksum(file):
			raise ValueError(f"Freigabe-Prüfsumme von {name} widerspricht der Datei")
	with files["gartenstrassen.pmtiles"].open("rb") as file:
		if file.read(8) != b"PMTiles\x03":
			raise ValueError("Ungültiger PMTiles-v3-Header")
	report = json.loads(files["bericht.json"].read_text(encoding="utf-8"))
	if not isinstance(report.get("gip_ids"), int) or report["gip_ids"] < 10000:
		raise ValueError("Bericht enthält keine Wien-weiten GIP-Abschnitte")
	if report.get("grm_available") is not True:
		raise ValueError("Baumkronen-Auswertung fehlt; work/ bleibt erhalten")
	if (release.get("manifest_sha256") != report.get("manifest_sha256")
		or release.get("gip_ids") != report["gip_ids"]
		or release.get("publication_fow") != [2,3,14]
		or release.get("min_area_m2") != 100):
		raise ValueError("Freigabemarker widerspricht Messbericht/FOW-Regel")
	if (report.get("geojson_sha256") != release["files_sha256"]["gip_abschnitte.geojson"]
		or report.get("csv_sha256") != release["files_sha256"]["gip_abschnitte.csv"]):
		raise ValueError("GeoJSON/CSV-Messquellen sind nicht identisch mit der Freigabe")
	measurement = work / "wien" / "ergebnisse" / "bericht.json"
	if not measurement.is_file() or checksum(measurement) != checksum(files["bericht.json"]):
		raise ValueError("Veröffentlichter Bericht entspricht nicht dem aktuellen Arbeitslauf")
	# Vor dem Entfernen der einzigen temporären QA-Geopackage zusätzlich
	# prüfen, ob sie zur eben veröffentlichten Partition gehört.
	qa = work / "wien" / "qa.gpkg"
	if qa.is_symlink() or not qa.is_file():
		raise FileNotFoundError("Wiener QA-GeoPackage fehlt")
	with sqlite3.connect(f"file:{qa.resolve()}?mode=ro",uri=True) as db:
		provenance = {key:json.loads(value) for key,value in
			db.execute("SELECT key,value FROM qa_provenienz")}
		if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
			raise ValueError("Wiener QA-Datenbank beschädigt")
	if (provenance.get("manifest_sha256") != report["manifest_sha256"]
		or provenance.get("gip_sha256") != report.get("gip_sha256")
		or provenance.get("partition_sha256") != report.get("partition_sha256")):
		raise ValueError("Wiener QA gehört nicht zur veröffentlichten Berechnung")
	manifest = work / "wien" / "raster.json"
	if not manifest.is_file() or report.get("manifest_sha256") != checksum(manifest):
		raise ValueError("Ausgabe und Wiener Rastermanifest stimmen nicht überein")
	with files["gip_abschnitte.csv"].open(newline="", encoding="utf-8") as file:
		reader = csv.DictReader(file)
		if not {"gip_id", "fow", "abschnitt_flaeche_m2"}.issubset(reader.fieldnames or []):
			raise ValueError("CSV-Spalten fehlen")
		count = sum(1 for _ in reader)
	if count != report["gip_ids"]:
		raise ValueError(f"CSV hat {count} statt {report['gip_ids']} GIP-Zeilen")
	with files["gip_abschnitte.geojson"].open("rb") as file:
		if not file.read(256).lstrip().startswith(b'{"type":"FeatureCollection"'):
			raise ValueError("GeoJSON-Header ungültig")
	return {"gip_ids": count, "manifest_sha256": report["manifest_sha256"],
		"output_bytes": sum(file.stat().st_size for file in files.values())}


def clean(repo, *, apply=False):
	repo = Path(repo).resolve()
	checked = verify(repo)
	print("Wien-Ausgabe geprüft:", json.dumps(checked, ensure_ascii=False))
	if apply:
		shutil.rmtree(repo / "work")
		print("Nur work/ wurde entfernt; raw/, output/ und Windows-Downloads bleiben erhalten.")
	else:
		print("Nur Prüfung. work/ bleibt erhalten (zum Löschen --apply).")


def main():
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("--apply", action="store_true")
	args = p.parse_args()
	clean(REPO, apply=args.apply)


if __name__ == "__main__":
	main()
