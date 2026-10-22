#!/usr/bin/env bash
# Original LINEAR_USE -> native CGAL preview -> validated Polygon-by-edge_id dissolve.
# NO SIS, no point-site reassignment and no spatial owner recovery.
set -euo pipefail

cd "$(dirname "$0")/../.."
REPO="$PWD"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
CACHE="$REPO/cache/wien/linear_use_original.sqlite"
AOI="$REPO/cache/wien/aoi.geojson"
BUILD="$REPO/build/cgal"
BIN="$BUILD/cgal_voronoi_faces"
OUT="$REPO/output/cgal_native_faces_inner_points_pre_sis_wien.geojson"

[[ -x "$PYTHON" ]] || { echo "Python fehlt: $PYTHON" >&2; exit 1; }
[[ -f "$CACHE" && -f "$AOI" ]] || {
	echo "Wiener Original-LINEAR_USE-Daten oder AOI fehlen" >&2; exit 1;
}
[[ ! -L "$REPO/output" ]] || { echo "output/ darf kein Symlink sein" >&2; exit 1; }
[[ ! -e "$OUT" && ! -L "$OUT" ]] || {
	echo "Vorhandenes GeoJSON wird nicht überschrieben: $OUT" >&2; exit 1;
}
command -v cmake >/dev/null || { echo "cmake fehlt" >&2; exit 1; }
cmake -S "$REPO/code/cgal" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD" --parallel 2

# Die strenge Face-Rekonstruktion ist noch nicht freigegeben.
# Zunächst die bekannte, selektierte Segment-/Punkt-Vorschau sicherstellen.
(cd "$REPO/code" && "$PYTHON" -m scripts.build_cgal_native_faces_pre_sis \
	--cache "$CACHE" \
	--aoi "$AOI" \
	--binary "$BIN" \
	--out "$OUT" \
	--preview-only \
	"$@")

# --preview-only bleibt als explizite Diagnoseoption verfügbar.
for option in "$@"; do
	if [[ "$option" == "--preview-only" ]]; then
		exit 0
	fi
done

# Ab hier werden nur gültige, zusammenhängende Einzelpolygone
# aus Faces mit gleicher originaler edge_id übernommen.
PREVIEW="$REPO/output/cgal_native_faces_inner_points_pre_sis_wien__preview.geojson"
DEBUG="$REPO/output/cgal_native_faces_inner_points_pre_sis_wien__dissolve_debug.geojson"
REPORT="$REPO/output/cgal_native_faces_inner_points_pre_sis_wien__dissolve_report.json"
(cd "$REPO/code" && "$PYTHON" -m scripts.dissolve_cgal_preview \
	--preview "$PREVIEW" \
	--out "$OUT" \
	--debug "$DEBUG" \
	--report "$REPORT")
