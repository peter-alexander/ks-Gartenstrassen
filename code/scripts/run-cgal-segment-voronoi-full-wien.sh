#!/usr/bin/env bash
# Full-Vienna CGAL comparison, independent of the small-case benchmark.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(cd .. && pwd -P)"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
CACHE="$REPO/cache/wien/linear_use.sqlite"
AOI="$REPO/cache/wien/aoi.geojson"
SUSPECTS="$REPO/output/boost_segment_voronoi_reverse_round3_minimal.geojson"
BIN="$REPO/build/cgal/cgal_segment_benchmark"
OUT="$REPO/output/cgal_segment_voronoi_full.json"

[[ -x "$PYTHON" ]] || { echo "Python-Venv fehlt: $PYTHON" >&2; exit 1; }
[[ -x "$BIN" ]] || { echo "CGAL-Binary fehlt: $BIN (zuerst kleinen Starter ausführen)" >&2; exit 1; }
[[ -f "$CACHE" && -f "$AOI" && -f "$SUSPECTS" ]] || {
	echo "Wien-Cache, AOI oder Diagnose-GeoJSON fehlen" >&2
	exit 1
}

"$PYTHON" -m scripts.benchmark_cgal_segment_voronoi \
	--cache "$CACHE" \
	--aoi "$AOI" \
	--suspects "$SUSPECTS" \
	--binary "$BIN" \
	--out "$OUT" \
	--timeout 300 \
	--validate \
	--full --only-full \
	"$@"
