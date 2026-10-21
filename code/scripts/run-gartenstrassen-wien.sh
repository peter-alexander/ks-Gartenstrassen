#!/usr/bin/env bash
# Original LINEAR_USE -> CGAL/SIS GeoJSON -> PMTiles preview.
set -euo pipefail

cd "$(dirname "$0")/../.."
REPO="$PWD"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
GEOJSON="$REPO/output/cgal_original_line_intersections_sis_wien.geojson"
PMTILES="$REPO/output/cgal_original_line_intersections_sis_wien.pmtiles"
REPORT="$REPO/output/cgal_original_line_intersections_sis_wien__zuordnungsbericht.json"
AXES="$REPO/cache/wien/linear_use_original.sqlite"
SIS="$REPO/cache/sis-wien.sqlite"

[[ -x "$PYTHON" ]] || { echo "Python fehlt: $PYTHON" >&2; exit 1; }
[[ ! -L "$REPO/output" && ! -L "$REPO/cache" ]] || {
	echo "output/ und cache/ dürfen keine Symlinks sein" >&2; exit 1;
}
mkdir -p "$REPO/output"

# Source acquisition is deliberately separate; only prepare when needed.
if [[ ! -f "$REPO/cache/wien/raster.json" || ! -f "$SIS" ||
	! -d "$REPO/cache/wien/strassenraum" ||
	! -d "$REPO/cache/wien/masken" ]]; then
	echo "Wiener SIS/GRM-Vorbereitung fehlt: starte sie jetzt."
	bash "$REPO/code/scripts/run-sis-v2-wien.sh"
fi

if [[ ! -f "$AXES" ]]; then
	if [[ -e "$REPO/output/linear_use_original.geojson" ]]; then
		echo "Original-GeoJSON vorhanden, SQLite fehlt: inkonsistenter Cache" >&2
		exit 1
	fi
	bash "$REPO/code/scripts/run-linear-use-wien.sh"
fi

if [[ ! -f "$GEOJSON" ]]; then
	bash "$REPO/code/scripts/run-cgal-voronoi-debug-wien.sh"
fi
[[ -s "$GEOJSON" ]] || { echo "CGAL-GeoJSON fehlt/leer" >&2; exit 1; }

# The generator performs original-line intersections before SIS and
# writes a fresh diagnostic report. No synthetic sample-point audit.
[[ -s "$REPORT" ]] || {
	echo "LINEAR_USE-Schnittbericht fehlt: $REPORT" >&2
	exit 1
}
"$PYTHON" - "$REPORT" <<'PY'
import json
import sys
from pathlib import Path
try:
	r=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
	assert r["schema"]=="original-line-polygon-intersections-v1"
	assert r["lines_multiple_polygons"]==0
	assert r["lines_no_polygon"]==0
	assert r["polygons_conflicting_edge_ids"]==0
	assert r["polygons_without_unambiguous_edge_id"]==0
	assert r["polygons_unambiguously_assigned"]==r["polygon_count"]
	print("LINEAR_USE-Flächenzuordnung: eindeutig; Bericht:",sys.argv[1])
except (OSError,ValueError,KeyError,AssertionError,TypeError) as exc:
	print("LINEAR_USE-Flächenzuordnung ungeklärt oder Bericht unbrauchbar:",
		exc,file=sys.stderr)
	sys.exit(1)
PY

if [[ -e "$PMTILES" || -L "$PMTILES" ]]; then
	echo "Vorhandene PMTiles wird nicht überschrieben: $PMTILES"
	exit 0
fi

command -v tippecanoe >/dev/null || {
	echo "tippecanoe fehlt. Bitte installieren (z.B. aus mapbox/tippecanoe bauen)." >&2
	exit 1
}
# tippecanoe can write PMTiles directly. Write to a staging file to avoid
# presenting partial archives as completed previews.
STAGE="$REPO/output/.cgal_original_line_intersections_sis_wien.$.pmtiles"
trap 'rm -f -- "$STAGE"' EXIT
tippecanoe -o "$STAGE" -l gartenstrassen -Z 8 -z 15 \
	--no-feature-limit --no-tile-size-limit \
	"$GEOJSON"
[[ -s "$STAGE" ]] || { echo "PMTiles-Ausgabe fehlt/leer" >&2; exit 1; }
if [[ -e "$PMTILES" || -L "$PMTILES" ]]; then
	echo "Zieldatei wurde inzwischen angelegt; kein Überschreiben" >&2
	exit 1
fi
mv -- "$STAGE" "$PMTILES"
echo "GeoJSON: $GEOJSON"
echo "PMTiles: $PMTILES"
echo "CGAL/SIS-PMTiles zur Sichtprüfung; Schnittzuordnung ohne Konflikte."
