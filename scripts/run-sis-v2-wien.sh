#!/usr/bin/env bash
# Wienweiter SIS-V2-Lauf: Wiener Arbeitsdaten im lokalen Repo (data/wien, gitignored).
set -euo pipefail
cd "$(dirname "$0")/.."

REPO_ROOT="$(pwd)"
ROOT="${SIS_WIEN_ROOT:-$REPO_ROOT/data/wien}"
PYTHON="${PYTHON:-.venv/bin/python}"
GIP2="${GIP2_SOURCE:-data/raw/gip_network_ogd.gpkg}"
AOI="${SIS_WIEN_AOI:-$ROOT/aoi/wien.geojson}"
ANALYSIS="$ROOT/analysis/wien"
DB="$ROOT/sis-wien.sqlite"
CACHE="$ROOT/wfs-kacheln"

# Auf Windows-Mounts muss die eigentliche Partition eingehängt sein.
# Für native WSL-Pfade ist das Zielverzeichnis bewusst vorab anzulegen;
# ein Tippfehler darf keinen stillen Daten-Neulauf starten.
case "$ROOT" in
	/mnt/e/*)
		[[ -d /mnt/e ]] && mountpoint -q /mnt/e || {
			echo "Abbruch: /mnt/e ist kein eingehängtes Laufwerk" >&2
			exit 1
		}
		;;
	/*)
		[[ -d "$ROOT" ]] || {
			echo "Abbruch: SIS_WIEN_ROOT existiert nicht: $ROOT" >&2
			exit 1
		}
		;;
	*)
		echo "Abbruch: SIS_WIEN_ROOT muss ein absoluter Pfad sein" >&2
		exit 1
		;;
esac
mkdir -p "$ROOT"
[[ -w "$ROOT" ]] || { echo "Abbruch: Datenverzeichnis nicht beschreibbar: $ROOT" >&2; exit 1; }
[[ -f "$GIP2" ]] || { echo "GIP2-Quelle fehlt: $GIP2" >&2; exit 1; }
mkdir -p "$ROOT/aoi" "$ANALYSIS"
if [[ ! -f "$AOI" ]]; then
	"$PYTHON" -m scripts.wienwide_aoi --wien --out-dir "$ROOT/aoi"
fi
[[ -f "$AOI" ]] || { echo "Wien-AOI fehlt: $AOI" >&2; exit 1; }

# Bereits abgeschlossene WFS-Kacheln und SQLite-Features werden wiederverwendet.
"$PYTHON" -m scripts.sis_wien_index --aoi "$AOI" --cache "$CACHE" --database "$DB"
if [[ ! -f "$ANALYSIS/aoi.geojson" ]]; then
	cp -- "$AOI" "$ANALYSIS/aoi.geojson"
elif ! cmp -s "$AOI" "$ANALYSIS/aoi.geojson"; then
	echo "Wien-AOI hat sich geändert; vorhandenen Analysezustand nicht überschreiben" >&2
	exit 1
fi

PYTHON="$PYTHON" GIP2_SOURCE="$GIP2" SIS_V2_ROOT="$ANALYSIS" SIS_V2_INDEX="$DB" \
	bash scripts/run-sis-v2-pilot.sh --from grid "$@"
