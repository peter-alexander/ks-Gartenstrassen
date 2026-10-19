#!/usr/bin/env bash
# Diagnose real GIP neighbors of the isolated Boost segment in Vienna.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(cd .. && pwd -P)"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
CACHE="$REPO/cache/wien/linear_use.sqlite"
AOI="$REPO/cache/wien/aoi.geojson"
SUSPECTS="$REPO/output/boost_segment_voronoi_diagnose_continued_suspects.geojson"
OUT="$REPO/output/boost_segment_voronoi_neighbors.json"

[[ -x "$PYTHON" ]] || { echo "Python-Venv fehlt: $PYTHON" >&2; exit 1; }
[[ -f "$CACHE" && -f "$AOI" ]] || {
	echo "LINEAR_USE-Cache oder Wien-AOI fehlt" >&2
	exit 1
}
[[ -f "$SUSPECTS" ]] || {
	echo "Fortgesetzte Diagnose fehlt: $SUSPECTS" >&2
	exit 1
}

"$PYTHON" -m scripts.investigate_boost_neighbors \
	--cache "$CACHE" \
	--aoi "$AOI" \
	--suspects "$SUSPECTS" \
	--out "$OUT" \
	"$@"
