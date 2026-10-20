#!/usr/bin/env bash
# Existing Vienna caches -> LINEAR_USE -> CGAL/SIS GeoJSON -> PMTiles preview.
set -euo pipefail

cd "$(dirname "$0")/../.."
REPO="$PWD"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
GEOJSON="$REPO/output/cgal_segment_voronoi_sis_wien.geojson"
PMTILES="$REPO/output/cgal_segment_voronoi_sis_wien.pmtiles"
AUDIT="$REPO/output/cgal_cell_ownership_audit.json"
AXES="$REPO/cache/wien/linear_use.sqlite"
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
	if [[ -e "$REPO/output/linear_use_mittelachsen.geojson" ]]; then
		echo "LINEAR_USE-GeoJSON vorhanden, SQLite fehlt: inkonsistenter Cache" >&2
		exit 1
	fi
	bash "$REPO/code/scripts/run-linear-use-wien.sh"
fi

if [[ ! -f "$GEOJSON" ]]; then
	bash "$REPO/code/scripts/run-cgal-voronoi-debug-wien.sh"
fi
[[ -s "$GEOJSON" ]] || { echo "CGAL-GeoJSON fehlt/leer" >&2; exit 1; }

# Audit is diagnostic for an experimental preview. Preserve report on failure.
if [[ ! -e "$AUDIT" ]]; then
	echo "Prüfe Zellzuordnung (Stichproben) ..."
	if ! (cd "$REPO/code" && "$PYTHON" -m scripts.audit_cgal_cell_ownership \
		--cache "$AXES" --geojson "$GEOJSON" --out "$AUDIT"); then
		echo "WARNUNG: Zellzuordnung nicht bestanden; siehe $AUDIT" >&2
		echo "PMTiles bleibt ausdrücklich eine experimentelle Sichtprüfung." >&2
	fi
fi

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
STAGE="$REPO/output/.cgal_segment_voronoi_sis_wien.$$.pmtiles"
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
echo "Hinweis: experimentelle CGAL-Flächen, nicht fachlich freigegeben."
