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

REPO = Path(__file__).resolve().parents[1]


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
	with files["gartenstrassen.pmtiles"].open("rb") as file:
		if file.read(8) != b"PMTiles\\x03":
			raise ValueError("Ungültiger PMTiles-v3-Header")
	report = json.loads(files["bericht.json"].read_text(encoding="utf-8"))
	if not isinstance(report.get("gip_ids"), int) or report["gip_ids"] < 10000:
		raise ValueError("Bericht enthält keine Wien-weiten GIP-Abschnitte")
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
