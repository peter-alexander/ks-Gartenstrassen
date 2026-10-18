"""One-time, resumable relocation of Vienna data into raw/, work/, output/.

Default: dry run. --apply: move files, never silently overwrite.
--prune-legacy --apply: remove only named, reviewed former data trees.
--clean-work --apply: remove reproducible working data after output verification.
Nothing here modifies tracked source files or downloads new data.
"""
import argparse
from pathlib import Path
import json
import shutil
import sqlite3

REPO = Path(__file__).resolve().parents[1]

# Child paths must be moved before their containing analysis tree.
MOVES = (
	("data/raw/gip_network_ogd.gpkg", "raw/gip_network_ogd.gpkg"),
	("data/raw/FMZK_WIEN_GP.gpkg", "raw/FMZK_WIEN_GP.gpkg"),
	("data/raw/SISBELAGOGD.json", "raw/SISBELAGOGD.json"),
	("data/cache/kataster", "raw/kataster"),
	("data/wien/wfs-kacheln", "raw/sis/wfs-kacheln"),
	("data/wien/aoi", "raw/aoi"),
	("data/wien/analysis/wien/grm2023/png", "raw/grm2023/png"),
	("data/wien/sis-wien.sqlite", "work/sis-wien.sqlite"),
	("data/wien/analysis/wien/ergebnisse", "output"),
	("data/wien/analysis/wien/gartenstrassen_sis_v2.pmtiles",
		"output/gartenstrassen.pmtiles"),
	("data/wien/analysis/wien", "work/wien"),
)
REQUIRED = {
	"data/raw/gip_network_ogd.gpkg",
	"data/wien/wfs-kacheln",
	"data/wien/aoi",
	"data/wien/analysis/wien/grm2023/png",
	"data/wien/sis-wien.sqlite",
	"data/wien/analysis/wien/ergebnisse",
	"data/wien/analysis/wien/gartenstrassen_sis_v2.pmtiles",
	"data/wien/analysis/wien",
}
LEGACY_DELETE = ("data/processed", "data/cache", "data/wien")


def resolved_root(root):
	root = Path(root).resolve()
	if not (root / ".git").exists():
		raise ValueError(f"Kein Git-Repository: {root}")
	return root


def ensure_safe_path(root, relative):
	path = root / relative
	if not path.is_relative_to(root):
		raise ValueError(f"Pfad außerhalb des Repositorys: {path}")
	part = root
	for name in Path(relative).parts:
		part /= name
		if part.is_symlink():
			raise ValueError(f"Symlink ist nicht erlaubt: {part}")
	return path


def plan(root):
	root = resolved_root(root)
	items = []
	for src_rel, dest_rel in MOVES:
		src = ensure_safe_path(root, src_rel)
		dst = ensure_safe_path(root, dest_rel)
		if src.exists() and dst.exists():
			raise FileExistsError(f"Quelle und Ziel gleichzeitig vorhanden: {src} / {dst}")
		if src.exists():
			status = "verschieben"
		elif dst.exists():
			status = "bereits_verschoben"
		elif src_rel in REQUIRED:
			raise FileNotFoundError(f"Benötigter Wiener Datenbestand fehlt: {src_rel}")
		else:
			status = "nicht_vorhanden"
		items.append((src, dst, status))
	return items


def check_wien(root):
	from scripts.diagnose_parallel_gip import require_complete_wien

	work = root / "work" / "wien"
	gip = work / "gip.sqlite"
	manifest = work / "raster.json"
	if not gip.is_file() or not manifest.is_file():
		raise FileNotFoundError("Wien-GIP und Rastermanifest fehlen unter work/wien")
	return require_complete_wien(gip, manifest)


def check_output(root):
	out = ensure_safe_path(root, "output")
	for name in ("gip_abschnitte.geojson", "gip_abschnitte.csv",
			"bericht.json", "gartenstrassen.pmtiles"):
		file = ensure_safe_path(root, "output/" + name)
		if not file.is_file() or not file.stat().st_size:
			raise FileNotFoundError(f"Ausgabe fehlt/ist leer: {file}")
	with (out / "gartenstrassen.pmtiles").open("rb") as source:
		if source.read(8) != b"PMTiles\x03":
			raise ValueError("PMTiles-Header ungültig")
	report = json.loads((out / "bericht.json").read_text(encoding="utf-8"))
	if not report.get("gip_ids") or not report.get("manifest_sha256"):
		raise ValueError("Wien-Bericht unvollständig")
	return {"gip_ids": report["gip_ids"], "archive_bytes":
		(out / "gartenstrassen.pmtiles").stat().st_size}


def relocate(root, *, apply=False):
	items = plan(root)
	for src, dst, status in items:
		print(f"{status}: {src.relative_to(root)} -> {dst.relative_to(root)}", flush=True)
	if not apply:
		print("Nur Vorschau. Keine Datei verändert.")
		return
	for src, dst, status in items:
		if status != "verschieben":
			continue
		dst.parent.mkdir(parents=True, exist_ok=True)
		# The working repository and legacy data directory are on the same WSL disk.
		# rename is atomic and avoids a second multi-GB copy.
		src.rename(dst)
		print(f"OK: {dst.relative_to(root)}", flush=True)
	# Verifies the FULL city index/manifest and the actual final output.
	print("Prüfung Wiener GIP:", check_wien(root))
	print("Prüfung Veröffentlichung:", check_output(root))


def purge(root, path, *, apply=False):
	target = ensure_safe_path(root, path)
	if not target.exists():
		print(f"Fehlt bereits: {path}")
		return
	if not target.is_dir():
		raise ValueError(f"Nur Verzeichnisse werden gelöscht: {path}")
	print(f"{'LÖSCHEN' if apply else 'WÜRDE LÖSCHEN'}: {path}")
	if apply:
		shutil.rmtree(target)


def cleanup(root, *, apply=False, legacy=False):
	# End results verified BEFORE any deletion; never delete raw/.
	result = check_output(root)
	print("Ergebnisprüfung:", result)
	if legacy:
		if not (root / "raw" / "gip_network_ogd.gpkg").is_file():
			raise FileNotFoundError("GIP-Rohdatei fehlt – alte Daten nicht löschen")
		if not (root / "raw" / "sis" / "wfs-kacheln").is_dir():
			raise FileNotFoundError("SIS-WFS-Cache fehlt – alte Daten nicht löschen")
		if not (root / "raw" / "grm2023" / "png").is_dir():
			raise FileNotFoundError("GRM-Rohdateien fehlen – alte Daten nicht löschen")
		for path in LEGACY_DELETE:
			purge(root, path, apply=apply)
	else:
		purge(root, "work", apply=apply)


def main():
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("--root", type=Path, default=REPO)
	p.add_argument("--apply", action="store_true",
		help="Aktion nach Prüfung wirklich ausführen; Standard ist Vorschau")
	mode = p.add_mutually_exclusive_group()
	mode.add_argument("--prune-legacy", action="store_true",
		help="Nur alte data/processed, data/cache, data/wien nach erfolgreichem Umzug entfernen")
	mode.add_argument("--clean-work", action="store_true",
		help="Nur work/ nach vollständig geprüften Endergebnissen entfernen")
	a = p.parse_args()
	root = resolved_root(a.root)
	if a.prune_legacy or a.clean_work:
		cleanup(root, apply=a.apply, legacy=a.prune_legacy)
	else:
		relocate(root, apply=a.apply)


if __name__ == "__main__":
	main()
