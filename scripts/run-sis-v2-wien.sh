#!/usr/bin/env bash
# Ein einziger Wien-Lauf: unveränderliche Rohdaten, berechenbare Arbeitsdaten, Ergebnisse.
set -euo pipefail
cd "$(dirname "$0")/.."

REPO="$(pwd -P)"
RAW="$REPO/raw"
WORK="$REPO/work"
OUT="$REPO/output"
ANALYSIS="$WORK/wien"
DB="$WORK/sis-wien.sqlite"
CACHE="$RAW/sis/wfs-kacheln"
GIP2="$RAW/gip_network_ogd.gpkg"
AOI="$RAW/aoi/wien.geojson"
PYTHON="${PYTHON:-.venv/bin/python}"

if [[ -n "${SIS_WIEN_ROOT:-}" ]]; then
	echo "SIS_WIEN_ROOT ist veraltet. Nur noch raw/, work/, output/ verwenden." >&2
	exit 2
fi

[[ -d "$RAW" && ! -L "$RAW" ]] || {
	echo "Rohdatenverzeichnis fehlt: $RAW. Zuerst Datenmigration durchführen." >&2
	exit 1
}
[[ ! -L "$WORK" && ! -L "$OUT" ]] || {
	echo "work/ und output/ dürfen keine Symlinks sein." >&2
	exit 1
}
[[ -x "$PYTHON" ]] || { echo "Python-Venv fehlt: $PYTHON" >&2; exit 1; }

# PMTiles-Nachbau benötigt nur das fertige GeoJSON, keine erneute WFS-Indexierung.
if [[ "${1:-}" == "--from" && "${2:-}" == "pmtiles" ]]; then
	SIS_V2_RAW_ROOT="$RAW" SIS_V2_ROOT="$ANALYSIS" \
	SIS_V2_PUBLISH_DIR="$OUT" SIS_V2_GRM_RAW_ROOT="$RAW/grm2023" \
		PYTHON="$PYTHON" bash scripts/run-sis-v2-pilot.sh "$@"
	exit 0
fi

[[ -f "$GIP2" ]] || { echo "GIP2-Original fehlt: $GIP2" >&2; exit 1; }
[[ -d "$CACHE" ]] || { echo "SIS-WFS-Kacheln fehlen: $CACHE" >&2; exit 1; }
mkdir -p "$RAW/aoi" "$ANALYSIS"
if [[ ! -f "$AOI" ]]; then
	"$PYTHON" -m scripts.wienwide_aoi --wien --out-dir "$RAW/aoi"
fi
[[ -f "$AOI" ]] || { echo "Wien-AOI fehlt: $AOI" >&2; exit 1; }

# Vorhandene WFS-Rohantworten bleiben im raw/-Cache. Der Index ist temporär.
"$PYTHON" -m scripts.sis_wien_index --aoi "$AOI" --cache "$CACHE" --database "$DB"
if [[ ! -f "$ANALYSIS/aoi.geojson" ]]; then
	cp -- "$AOI" "$ANALYSIS/aoi.geojson"
elif ! cmp -s "$AOI" "$ANALYSIS/aoi.geojson"; then
	echo "AOI wurde geändert; vorhandene Wiener Arbeitsdaten nicht überschreiben." >&2
	exit 1
fi

SIS_V2_RAW_ROOT="$RAW" SIS_V2_ROOT="$ANALYSIS" \
	SIS_V2_INDEX="$DB" SIS_V2_PUBLISH_DIR="$OUT" \
	SIS_V2_GRM_RAW_ROOT="$RAW/grm2023" GIP2_SOURCE="$GIP2" PYTHON="$PYTHON" \
	bash scripts/run-sis-v2-pilot.sh --from grid "$@"
