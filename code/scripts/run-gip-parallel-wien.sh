#!/usr/bin/env bash
# One entrypoint for the *full* Wiener GIP2 graph, never a test tile.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(cd .. && pwd -P)"
ANALYSIS="$REPO/cache/wien"
WORK="$REPO/work/wien"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"

[[ -d "$ANALYSIS" && ! -L "$ANALYSIS" && ! -L "$WORK" ]] || {
	echo "Abbruch: Dauerhafter Wiener Cache fehlt oder ist Symlink: $ANALYSIS" >&2
	exit 1
}
[[ -x "$PYTHON" ]] || { echo "Python-Venv fehlt: $PYTHON" >&2; exit 1; }
[[ -f "$ANALYSIS/raster.json" && -f "$ANALYSIS/gip.sqlite" ]] || {
	echo "Abbruch: Vollständiger Wiener GIP-Index und Raster fehlen in $ANALYSIS" >&2
	exit 1
}
mkdir -p "$WORK"
"$PYTHON" -m scripts.diagnose_parallel_gip \
	--manifest "$ANALYSIS/raster.json" \
	--gip-index "$ANALYSIS/gip.sqlite" \
	--distance-m 20 \
	--out-dir "$WORK/gip-parallel-20m"
