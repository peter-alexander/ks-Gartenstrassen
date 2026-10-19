#!/usr/bin/env bash
# Independent CGAL benchmark; no changes to production or GIP geometries.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(cd .. && pwd -P)"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
CACHE="$REPO/cache/wien/linear_use.sqlite"
AOI="$REPO/cache/wien/aoi.geojson"
SUSPECTS="$REPO/output/boost_segment_voronoi_reverse_round3_minimal.geojson"
BUILD="$REPO/build/cgal"
BIN="$BUILD/cgal_segment_benchmark"
OUT="$REPO/output/cgal_segment_voronoi_benchmark.json"

[[ -x "$PYTHON" ]] || { echo "Python-Venv fehlt: $PYTHON" >&2; exit 1; }
[[ -f "$CACHE" && -f "$AOI" && -f "$SUSPECTS" ]] || {
	echo "Wien-Cache, AOI oder reduzierte Diagnose-GeoJSON fehlen" >&2
	exit 1
}
command -v cmake >/dev/null || { echo "cmake fehlt" >&2; exit 1; }

cmake -S "$REPO/code/cgal" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD" --parallel 2

"$PYTHON" -m scripts.benchmark_cgal_segment_voronoi \
	--cache "$CACHE" \
	--aoi "$AOI" \
	--suspects "$SUSPECTS" \
	--binary "$BIN" \
	--out "$OUT" \
	"$@"
