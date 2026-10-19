#!/usr/bin/env bash
# Isolate the baseline segments which interact with the pathological Boost site.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(cd .. && pwd -P)"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
CACHE="$REPO/cache/wien/linear_use.sqlite"
AOI="$REPO/cache/wien/aoi.geojson"
SUSPECTS="$REPO/output/boost_segment_voronoi_diagnose_continued_suspects.geojson"
OUT="$REPO/output/boost_segment_voronoi_reverse.json"

[[ -x "$PYTHON" ]] || { echo "Python-Venv fehlt: $PYTHON" >&2; exit 1; }
[[ -f "$CACHE" && -f "$AOI" && -f "$SUSPECTS" ]] || {
	echo "Benötigte Wiener Diagnose-Eingaben fehlen" >&2
	exit 1
}

"$PYTHON" -m scripts.reverse_diagnose_boost_voronoi \
	--cache "$CACHE" \
	--aoi "$AOI" \
	--suspects "$SUSPECTS" \
	--out "$OUT" \
	"$@"
