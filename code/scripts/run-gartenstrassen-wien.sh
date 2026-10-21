#!/usr/bin/env bash
# Original LINEAR_USE -> CGAL/SIS GeoJSON -> PMTiles preview.
set -euo pipefail

cd "$(dirname "$0")/../.."
REPO="$PWD"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
GEOJSON="$REPO/output/cgal_segment_voronoi_sis_wien.geojson"
PMTILES="$REPO/output/cgal_segment_voronoi_sis_wien.pmtiles"
AUDIT="$REPO/output/cgal_cell_ownership_audit.json"
AXES="$REPO/cache/wien/linear_use_original.sqlite"
SIS="$REPO/cache/sis-wien.sqlite"
ALLOW_FAILED_QA="${ALLOW_FAILED_QA:-0}"

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

# QA is regenerated if input is newer; a stale report must not pass.
if [[ ! -s "$AUDIT" || "$GEOJSON" -nt "$AUDIT" || "$AXES" -nt "$AUDIT" ]]; then
	if [[ -e "$AUDIT" || -L "$AUDIT" ]]; then
		echo "QA-Bericht ist veraltet: archiviere statt alte Resultate zu übernehmen."
		mv -- "$AUDIT" "$AUDIT.previous.$(date +%s).json"
	fi
	echo "Prüfe Zellzuordnung und Geometriegültigkeit ..."
	if ! (cd "$REPO/code" && "$PYTHON" -m scripts.audit_cgal_cell_ownership \
		--cache "$AXES" --geojson "$GEOJSON" --out "$AUDIT"); then
		[[ -s "$AUDIT" ]] || {
			echo "QA abgebrochen, kein Bericht erzeugt." >&2
			exit 1
		}
	fi
fi

# Exit non-zero on invalid, incomplete or outdated reports, unless an
# intentionally unverified visualization is explicitly requested.
QA_STATUS="$("$PYTHON" - "$AUDIT" <<'PY'
import json
import sys
from pathlib import Path
try:
	r=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
	assert r["qa_status"] in ("passed","failed")
	assert isinstance(r["ownership_failures"],int)
	assert isinstance(r["invalid_geometry_count"],int)
	assert r["failures"]==r["ownership_failures"]+r["invalid_geometry_count"]
	print(r["qa_status"])
except (OSError,ValueError,KeyError,AssertionError,TypeError) as exc:
	print(f"QA-Bericht unbrauchbar: {exc}",file=sys.stderr)
	sys.exit(2)
PY
)" || exit 1
echo "QA-Status: $QA_STATUS | Bericht: $AUDIT"
if [[ "$QA_STATUS" != passed ]]; then
	echo "QA fehlgeschlagen: keine automatische Freigabe der PMTiles." >&2
	if [[ "$ALLOW_FAILED_QA" != 1 ]]; then
		echo "Nur für bewusst ungeprüfte Sichtprüfung: ALLOW_FAILED_QA=1" >&2
		exit 1
	fi
	echo "Ungeprüfte Vorschau wird ausdrücklich erlaubt." >&2
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
echo "CGAL/SIS-PMTiles zur Sichtprüfung; maßgeblich ist der oben ausgewiesene QA-Status."
