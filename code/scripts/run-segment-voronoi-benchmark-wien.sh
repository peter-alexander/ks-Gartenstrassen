#!/usr/bin/env bash
# Independent time-limited benchmark; does not modify SIS or Voronoi output.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(cd .. && pwd -P)"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
CACHE="$REPO/cache/wien/linear_use.sqlite"
AOI="$REPO/cache/wien/aoi.geojson"
OUT="$REPO/output/boost_segment_voronoi_benchmark.json"

[[ -x "$PYTHON" ]] || { echo "Python-Venv fehlt: $PYTHON" >&2; exit 1; }
[[ -f "$CACHE" && -f "$AOI" ]] || {
	echo "LINEAR_USE-Cache oder Wien-AOI fehlt" >&2
	exit 1
}
[[ ! -L "$REPO/output" ]] || { echo "output/ darf kein Symlink sein" >&2; exit 1; }

"$PYTHON" -m scripts.benchmark_segment_voronoi \
	--cache "$CACHE" \
	--aoi "$AOI" \
	--out "$OUT" \
	"$@"
