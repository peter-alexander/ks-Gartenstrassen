#!/usr/bin/env bash
# One entrypoint for the *full* Wiener GIP2 graph, never a test tile.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(pwd)"
ROOT="${SIS_WIEN_ROOT:-$REPO/data/wien}"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
ANALYSIS="$ROOT/analysis/wien"

[[ -d "$ROOT" ]] || {
	echo "Abbruch: Wiener Daten fehlen: $ROOT" >&2
	echo "Zuerst scripts/migrate-wien-data-into-repo.sh prüfen/ausführen." >&2
	exit 1
}
[[ -x "$PYTHON" ]] || { echo "Python-Venv fehlt: $PYTHON" >&2; exit 1; }
[[ -f "$ANALYSIS/raster.json" && -f "$ANALYSIS/gip.sqlite" ]] || {
	echo "Abbruch: Vollständiger Wiener GIP-Index und Raster fehlen in $ANALYSIS" >&2
	exit 1
}
"$PYTHON" -m scripts.diagnose_parallel_gip \
	--manifest "$ANALYSIS/raster.json" \
	--gip-index "$ANALYSIS/gip.sqlite" \
	--distance-m 20 \
	--out-dir "$ANALYSIS/gip-parallel-20m"
