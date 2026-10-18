#!/usr/bin/env bash
# Relocate the COMPLETE private Wien workspace into the ignored data/ tree.
# Deliberately do not prune data or add large files to Git history.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
SOURCE="\${GARTEN_SOURCE:-$HOME/Gartenstrassen}"
DEST="$REPO/data/wien"
PYTHON="\${PYTHON:-$REPO/.venv/bin/python}"
APPLY=0

usage() {
	cat <<'HELP'
Usage: bash scripts/migrate-wien-data-into-repo.sh [--apply]

Default: report/check ONLY. --apply moves ~/Gartenstrassen in its entirety
to <repo>/data/wien; no recursive deletion, no Git add, no re-download.
Environment: GARTEN_SOURCE (source override), PYTHON (venv interpreter).
Source and destination must be distinct; destination must not exist.
Check that no Wien job is running before moving its open SQLite files.
HELP
}

while (($#)); do
	case "$1" in
		--apply) APPLY=1;;
		-h|--help) usage; exit 0;;
		*) usage >&2; exit 2;;
	esac
	shift
done

[[ -d "$SOURCE" && ! -L "$SOURCE" ]] || {
	echo "Abbruch: WSL-Quellverzeichnis fehlt oder ist ein Symlink: $SOURCE" >&2
	exit 1
}
SOURCE="$(cd "$SOURCE" && pwd -P)"
case "$REPO/" in
	"$SOURCE/"*) echo "Abbruch: Repository liegt innerhalb der Quelldaten" >&2; exit 1;;
esac
case "$SOURCE/" in
	"$REPO/"*) echo "Abbruch: Quellordner liegt innerhalb des Repositorys" >&2; exit 1;;
esac
[[ ! -e "$DEST" && ! -L "$DEST" ]] || {
	echo "Abbruch: Ziel existiert bereits: $DEST. Keine Zusammenführung/Überschreibung." >&2
	exit 1
}
[[ -x "$PYTHON" ]] || {
	echo "Abbruch: Python-Venv nicht gefunden: $PYTHON" >&2
	exit 1
}

ANALYSIS="$SOURCE/analysis/wien"
for filename in "$ANALYSIS/aoi.geojson" "$ANALYSIS/raster.json" "$ANALYSIS/gip.sqlite"; do
	[[ -f "$filename" ]] || {
		echo "Abbruch: Wiener Primärdatei fehlt: $filename" >&2
		exit 1
	}
done
cd "$REPO"
"$PYTHON" - "$ANALYSIS/gip.sqlite" "$ANALYSIS/raster.json" <<'PY'
import sys
from scripts.diagnose_parallel_gip import require_complete_wien

checked = require_complete_wien(sys.argv[1], sys.argv[2])
print(f"Vollständigen Wien-Datensatz nachgewiesen: "
	f"{checked['aoi_km2']:.2f} km², {checked['tiles']} Rasterkacheln, "
	f"{checked['axes']} GIP-Achsen")
PY

echo "Quelle: $SOURCE"
echo "Ziel:   $DEST (Git-ignored)"
du -sh -- "$SOURCE" || true

if (( ! APPLY )); then
	echo "Nur geprüft. Zum Verschieben nach Beenden aller Wien-Jobs: --apply"
	exit 0
fi

mkdir -p -- "$REPO/data"
echo "Verschiebe gesamtes Wiener Arbeitsverzeichnis (inklusive WFS-/GRM-/SQLite-Caches)."
mv --no-target-directory -- "$SOURCE" "$DEST"
[[ -f "$DEST/analysis/wien/gip.sqlite" && -f "$DEST/analysis/wien/raster.json" ]] || {
	echo "FEHLER: Quelldaten am Ziel unvollständig. Bitte NICHT löschen." >&2
	exit 1
}
"$PYTHON" - "$DEST/analysis/wien/gip.sqlite" "$DEST/analysis/wien/raster.json" <<'PY'
import sys
from scripts.diagnose_parallel_gip import require_complete_wien

require_complete_wien(sys.argv[1], sys.argv[2])
print("Wien-Migration abgeschlossen; Manifest- und GIP-Indexprüfung am neuen Ort erfolgreich.")
PY
echo "Bestehende Test- und Pilotdaten in data/processed/ wurden NICHT angerührt."
echo "Hinweis: Auch der verschobene data/wien/ enthält ggf. alte Dateien."
echo "Bereinigung erst anhand der lokalen Bestandsaufnahme, nicht mit pauschalem rm -rf."
