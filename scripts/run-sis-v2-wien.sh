#!/usr/bin/env bash
# Wienweiter SIS-V2-Lauf: alle großen Daten ausschließlich auf /mnt/e.
set -euo pipefail
cd "$(dirname "$0")/.."

ROOT="/mnt/e/Gartenstrassen"
PYTHON="${PYTHON:-.venv/bin/python}"
GIP2="${GIP2_SOURCE:-data/raw/gip_network_ogd.gpkg}"
AOI="${SIS_WIEN_AOI:-$ROOT/aoi/wien.geojson}"
ANALYSIS="$ROOT/analysis/wien"
DB="$ROOT/sis-wien.sqlite"
CACHE="$ROOT/wfs-kacheln"

[[ -d /mnt/e ]] || { echo "Externes Laufwerk /mnt/e nicht eingehängt" >&2; exit 1; }
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
