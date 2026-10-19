#!/usr/bin/env bash
# Standalone: LINEAR_USE base_type=1 -> eine Mittelachse je edge_id für Wien.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(cd .. && pwd -P)"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
SOURCE="${GIP_NETWORK_SOURCE:-/mnt/c/Users/peter/Downloads/gip_network_ogd.gpkg}"
AOI="$REPO/cache/wien/aoi.geojson"
CACHE="$REPO/cache/wien/linear_use.sqlite"
GEOJSON="$REPO/output/linear_use_mittelachsen.geojson"

[[ -x "$PYTHON" ]] || { echo "Python-Venv fehlt: $PYTHON" >&2; exit 1; }
[[ -f "$SOURCE" && -r "$SOURCE" ]] || {
	echo "GIP-Netzwerk-GeoPackage fehlt/ist nicht lesbar: $SOURCE" >&2
	exit 1
}
[[ -f "$AOI" ]] || { echo "Wien-AOI fehlt: $AOI" >&2; exit 1; }
[[ ! -L "$REPO/cache" && ! -L "$REPO/output" ]] || {
	echo "cache/ und output/ dürfen keine Symlinks sein" >&2
	exit 1
}

mkdir -p "$REPO/cache/wien" "$REPO/output"

"$PYTHON" -m scripts.build_linear_use_axes \
	--source "$SOURCE" \
	--aoi "$AOI" \
	--out "$CACHE" \
	--geojson "$GEOJSON" \
	--sample-spacing-m 5
