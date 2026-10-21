#!/usr/bin/env bash
# True CGAL segment Voronoi -> debug polygons -> exact SIS intersection.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(cd .. && pwd -P)"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
CACHE="$REPO/cache/wien/linear_use_original.sqlite"
AOI="$REPO/cache/wien/aoi.geojson"
SIS_MANIFEST="$REPO/cache/wien/raster.json"
SIS_ROOT="$REPO/cache/wien/strassenraum"
BUILD="$REPO/build/cgal"
BIN="$BUILD/cgal_voronoi_edges"
OUT="$REPO/output/cgal_original_linear_use_sis_wien.geojson"

[[ -x "$PYTHON" ]] || { echo "Python-Venv fehlt: $PYTHON" >&2; exit 1; }
[[ -f "$CACHE" && -f "$AOI" && -f "$SIS_MANIFEST" && -d "$SIS_ROOT" ]] || {
	echo "Wiener LINEAR_USE-, AOI- oder SIS-Daten fehlen" >&2
	exit 1
}
[[ ! -L "$REPO/output" ]] || { echo "output/ darf kein Symlink sein" >&2; exit 1; }
command -v cmake >/dev/null || { echo "cmake fehlt" >&2; exit 1; }

cmake -S "$REPO/code/cgal" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD" --parallel 2

"$PYTHON" -m scripts.build_cgal_voronoi_geojson \
	--cache "$CACHE" \
	--aoi "$AOI" \
	--sis-manifest "$SIS_MANIFEST" \
	--sis-root "$SIS_ROOT" \
	--binary "$BIN" \
	--out "$OUT" \
	"$@"
