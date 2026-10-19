#!/usr/bin/env bash
# Ein einziger Wien-Lauf: unveränderliche Rohdaten, berechenbare Arbeitsdaten, Ergebnisse.
set -euo pipefail
cd "$(dirname "$0")/.."

REPO="$(cd .. && pwd -P)"
RAW="$REPO/raw"
CACHE_ROOT="$REPO/cache"
DATA="$CACHE_ROOT/wien"
WORK="$REPO/work"
OUT="$REPO/output"
ANALYSIS="$WORK/wien"
DB="$CACHE_ROOT/sis-wien.sqlite"
CACHE="$RAW/sis/wfs-kacheln"
GIP2="${GIP2_SOURCE:-/mnt/c/Users/peter/Downloads/gip_network_ogd.gpkg}"
AOI="$RAW/aoi/wien.geojson"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"

if [[ -n "${SIS_WIEN_ROOT:-}" ]]; then
	echo "SIS_WIEN_ROOT ist veraltet; neue Daten liegen in raw/, work/, output/." >&2
	exit 2
fi

[[ ! -L "$RAW" && ! -L "$CACHE_ROOT" && ! -L "$DATA" ]] || {
	echo "raw/ und cache/ dürfen keine Symlinks sein" >&2; exit 1
}
[[ ! -L "$WORK" && ! -L "$OUT" ]] || {
	echo "work/ und output/ dürfen keine Symlinks sein." >&2
	exit 1
}
[[ -x "$PYTHON" ]] || { echo "Python-Venv fehlt: $PYTHON" >&2; exit 1; }

# PMTiles-Nachbau benötigt nur das fertige GeoJSON, keine erneute WFS-Indexierung.
if [[ "${1:-}" == "--from" && "${2:-}" == "pmtiles" ]]; then
	SIS_V2_RAW_ROOT="$RAW" SIS_V2_ROOT="$ANALYSIS" \
	SIS_V2_CACHE_WIEN="$DATA" SIS_V2_PUBLISH_DIR="$OUT" SIS_V2_GRM_RAW_ROOT="$RAW/grm2023" \
		PYTHON="$PYTHON" bash scripts/run-sis-steps.sh "$@"
	exit 0
fi

[[ -f "$GIP2" && -r "$GIP2" ]] || {
	echo "Schreibgeschützte GIP2-Quelle fehlt/ist nicht lesbar: $GIP2" >&2
	exit 1
}
# Die Windows-Downloads werden niemals Ziel eines Downloads oder Exports.
mkdir -p "$RAW/aoi" "$CACHE" "$DATA" "$ANALYSIS" "$OUT"
if [[ ! -f "$AOI" ]]; then
	"$PYTHON" -m scripts.wienwide_aoi --wien --out-dir "$RAW/aoi"
fi
[[ -f "$AOI" ]] || { echo "Wien-AOI fehlt: $AOI" >&2; exit 1; }

# WFS-Rohantworten bleiben in raw/, der geprüfte SIS-Index dauerhaft in cache/.
"$PYTHON" -m scripts.sis_wien_index --aoi "$AOI" --cache "$CACHE" --database "$DB"
if [[ ! -f "$DATA/aoi.geojson" ]]; then
	cp -- "$AOI" "$DATA/aoi.geojson"
elif ! cmp -s "$AOI" "$DATA/aoi.geojson"; then
	echo "AOI wurde geändert; vorhandene Wiener Arbeitsdaten nicht überschreiben." >&2
	exit 1
fi

SIS_V2_RAW_ROOT="$RAW" SIS_V2_ROOT="$ANALYSIS" \
	SIS_V2_CACHE_WIEN="$DATA" SIS_V2_INDEX="$DB" SIS_V2_PUBLISH_DIR="$OUT" \
	SIS_V2_GRM_RAW_ROOT="$RAW/grm2023" GIP2_SOURCE="$GIP2" PYTHON="$PYTHON" \
	bash scripts/run-sis-steps.sh --from grid "$@"

# Nur nach einem vollständigen, erfolgreichen Lauf work/ aufräumen.
# Dauerhaft vorbereitete Daten in cache/ bleiben vollständig erhalten.
if (( $# == 0 )) && [[ "${SIS_WIEN_KEEP_WORK:-0}" != "1" ]]; then
	"$PYTHON" -m scripts.clean_wien_work --apply
fi
