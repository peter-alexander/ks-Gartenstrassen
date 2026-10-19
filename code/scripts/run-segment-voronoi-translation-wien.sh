#!/usr/bin/env bash
# Bounded Boost translation sensitivity and finite Voronoi geometry comparison.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(cd .. && pwd -P)"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
CACHE="$REPO/cache/wien/linear_use.sqlite"
AOI="$REPO/cache/wien/aoi.geojson"
SUSPECTS="$REPO/output/boost_segment_voronoi_reverse_round3_minimal.geojson"
OUT="$REPO/output/boost_segment_voronoi_translation.json"

[[ -x "$PYTHON" ]] || { echo "Python-Venv fehlt: $PYTHON" >&2; exit 1; }
[[ -f "$CACHE" && -f "$AOI" && -f "$SUSPECTS" ]] || {
	echo "Benötigte Wiener Diagnose-Eingaben fehlen" >&2
	exit 1
}

"$PYTHON" -m scripts.investigate_boost_translation \
	--cache "$CACHE" \
	--aoi "$AOI" \
	--suspects "$SUSPECTS" \
	--out "$OUT" \
	"$@"
