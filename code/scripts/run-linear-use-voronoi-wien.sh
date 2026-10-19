#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(cd .. && pwd -P)"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
CACHE="$REPO/cache/wien/linear_use.sqlite"
AOI="$REPO/cache/wien/aoi.geojson"
SIS_MANIFEST="$REPO/cache/wien/raster.json"
SIS_ROOT="$REPO/cache/wien/strassenraum"
OUT="$REPO/output/linear_use_voronoi_debug.geojson"

[[ -x "$PYTHON" ]] || { echo "Python-Venv fehlt: $PYTHON" >&2; exit 1; }
[[ -f "$CACHE" && -f "$AOI" && -f "$SIS_MANIFEST" && -d "$SIS_ROOT" ]] || {
	echo "LINEAR_USE-Cache, Wien-AOI oder SIS-Straßenraum fehlt" >&2
	exit 1
}
[[ ! -L "$REPO/output" ]] || { echo "output/ darf kein Symlink sein" >&2; exit 1; }

"$PYTHON" -m scripts.build_linear_use_voronoi \
	--cache "$CACHE" \
	--aoi "$AOI" \
	--sis-manifest "$SIS_MANIFEST" \
	--sis-root "$SIS_ROOT" \
	--out "$OUT" \
	"$@"
