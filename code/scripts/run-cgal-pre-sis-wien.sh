#!/usr/bin/env bash
# Original LINEAR_USE -> native CGAL segment sites -> dissolve. NO SIS.
set -euo pipefail

cd "$(dirname "$0")/../.."
REPO="$PWD"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
CACHE="$REPO/cache/wien/linear_use_original.sqlite"
AOI="$REPO/cache/wien/aoi.geojson"
BUILD="$REPO/build/cgal"
BIN="$BUILD/cgal_voronoi_edges"
OUT="$REPO/output/cgal_original_segment_sites_pre_sis_wien.geojson"

[[ -x "$PYTHON" ]] || { echo "Python fehlt: $PYTHON" >&2; exit 1; }
[[ -f "$CACHE" && -f "$AOI" ]] || {
	echo "Original-LINEAR_USE-Cache oder Wiener AOI fehlt" >&2
	exit 1
}
[[ ! -L "$REPO/output" ]] || {
	echo "output/ darf kein Symlink sein" >&2
	exit 1
}
[[ ! -e "$OUT" && ! -L "$OUT" ]] || {
	echo "Vorhandene Ausgabe wird nicht überschrieben: $OUT" >&2
	exit 1
}
command -v cmake >/dev/null || { echo "cmake fehlt" >&2; exit 1; }
cmake -S "$REPO/code/cgal" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD" --parallel 2

(cd "$REPO/code" && "$PYTHON" -m scripts.build_cgal_pre_sis \
	--cache "$CACHE" \
	--aoi "$AOI" \
	--binary "$BIN" \
	--out "$OUT" \
	"$@")
