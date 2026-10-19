#!/usr/bin/env bash
# Identify pathological Boost segment-site constellations in real Vienna data.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(cd .. && pwd -P)"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
CACHE="$REPO/cache/wien/linear_use.sqlite"
AOI="$REPO/cache/wien/aoi.geojson"
OUT="$REPO/output/boost_segment_voronoi_diagnose.json"

[[ -x "$PYTHON" ]] || { echo "Python-Venv fehlt: $PYTHON" >&2; exit 1; }
[[ -f "$CACHE" && -f "$AOI" ]] || {
	echo "LINEAR_USE-Cache oder Wien-AOI fehlt" >&2
	exit 1
}
[[ ! -L "$REPO/output" ]] || { echo "output/ darf kein Symlink sein" >&2; exit 1; }

"$PYTHON" -m scripts.diagnose_boost_voronoi \
	--cache "$CACHE" \
	--aoi "$AOI" \
	--out "$OUT" \
	"$@"
