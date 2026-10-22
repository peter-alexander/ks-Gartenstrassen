#!/usr/bin/env bash
# Current stage: LINEAR_USE -> native CGAL Voronoi faces -> edge_id dissolve, BEFORE SIS.
# SIS overlay/PMTiles are intentionally not run until this stage is reviewed.
set -euo pipefail

cd "$(dirname "$0")/../.."
REPO="$PWD"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
CACHE="$REPO/cache/wien/linear_use_original.sqlite"

[[ -x "$PYTHON" ]] || { echo "Python fehlt: $PYTHON" >&2; exit 1; }
[[ ! -L "$REPO/output" && ! -L "$REPO/cache" ]] || {
	echo "output/ und cache/ dürfen keine Symlinks sein" >&2; exit 1;
}
mkdir -p "$REPO/output"

if [[ ! -f "$CACHE" ]]; then
	if [[ -e "$REPO/output/linear_use_original.geojson" ]]; then
		echo "Original-GeoJSON vorhanden, SQLite fehlt: inkonsistenter Cache" >&2
		exit 1
	fi
	bash "$REPO/code/scripts/run-linear-use-wien.sh"
fi

bash "$REPO/code/scripts/run-cgal-native-faces-pre-sis-wien.sh" "$@"
echo "CGAL-Schritt abgeschlossen. SIS-Verschnitt bleibt ausgesetzt."
