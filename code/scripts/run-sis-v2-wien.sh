#!/usr/bin/env bash
# Wienweite Vorbereitung: Rohdaten dauerhaft in raw/, abgeleitete Daten in cache/.
set -euo pipefail
cd "$(dirname "$0")/.."

REPO="$(cd .. && pwd -P)"
RAW="$REPO/raw"
CACHE_ROOT="$REPO/cache"
DATA="$CACHE_ROOT/wien"
DB="$CACHE_ROOT/sis-wien.sqlite"
WFS_CACHE="$RAW/sis/wfs-kacheln"
AOI="$RAW/aoi/wien.geojson"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"

if [[ -n "${SIS_WIEN_ROOT:-}" ]]; then
	echo "SIS_WIEN_ROOT ist veraltet; Daten liegen in raw/ und cache/." >&2
	exit 2
fi

[[ ! -L "$RAW" && ! -L "$CACHE_ROOT" && ! -L "$DATA" ]] || {
	echo "raw/ und cache/ dürfen keine Symlinks sein" >&2
	exit 1
}
[[ -x "$PYTHON" ]] || { echo "Python-Venv fehlt: $PYTHON" >&2; exit 1; }

mkdir -p "$RAW/aoi" "$WFS_CACHE" "$DATA"
if [[ ! -f "$AOI" ]]; then
	"$PYTHON" -m scripts.wienwide_aoi --wien --out-dir "$RAW/aoi"
fi
[[ -f "$AOI" ]] || { echo "Wien-AOI fehlt: $AOI" >&2; exit 1; }

# WFS-Rohantworten bleiben in raw/, der geprüfte SIS-Index dauerhaft in cache/.
"$PYTHON" -m scripts.sis_wien_index \
	--aoi "$AOI" --cache "$WFS_CACHE" --database "$DB"

if [[ ! -f "$DATA/aoi.geojson" ]]; then
	cp -- "$AOI" "$DATA/aoi.geojson"
elif ! cmp -s "$AOI" "$DATA/aoi.geojson"; then
	echo "AOI wurde geändert; vorhandenen Cache nicht überschreiben." >&2
	exit 1
fi

SIS_V2_RAW_ROOT="$RAW" SIS_V2_CACHE_WIEN="$DATA" SIS_V2_INDEX="$DB" \
SIS_V2_GRM_RAW_ROOT="$RAW/grm2023" PYTHON="$PYTHON" \
	bash scripts/run-sis-steps.sh --from grid "$@"
