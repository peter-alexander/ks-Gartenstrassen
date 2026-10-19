#!/usr/bin/env bash
# Isolate the baseline segments which interact with the pathological Boost site.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(cd .. && pwd -P)"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
CACHE="$REPO/cache/wien/linear_use.sqlite"
AOI="$REPO/cache/wien/aoi.geojson"
SUSPECTS="$REPO/output/boost_segment_voronoi_diagnose_continued_suspects.geojson"
OUT="$REPO/output/boost_segment_voronoi_reverse.json"

if [[ "${1:-}" == "--resume" ]]; then
	shift
	SUSPECTS="$REPO/output/boost_segment_voronoi_reverse_minimal.geojson"
	OUT="$REPO/output/boost_segment_voronoi_reverse_continued.json"
elif [[ "${1:-}" == "--resume-latest" ]]; then
	shift
	SUSPECTS="$REPO/output/boost_segment_voronoi_reverse_continued_minimal.geojson"
	ROUND=3
	while [[ -f "$REPO/output/boost_segment_voronoi_reverse_round${ROUND}_minimal.geojson" ]]; do
		SUSPECTS="$REPO/output/boost_segment_voronoi_reverse_round${ROUND}_minimal.geojson"
		ROUND=$((ROUND + 1))
	done
	OUT="$REPO/output/boost_segment_voronoi_reverse_round${ROUND}.json"
	if [[ -e "$OUT" ]]; then
		echo "Diagnosebericht existiert bereits ohne fertige GeoJSON: $OUT" >&2
		exit 1
	fi
	printf 'Fortsetzung von %s nach %s\\n' "$SUSPECTS" "$OUT"
fi

[[ -x "$PYTHON" ]] || { echo "Python-Venv fehlt: $PYTHON" >&2; exit 1; }
[[ -f "$CACHE" && -f "$AOI" && -f "$SUSPECTS" ]] || {
	echo "Benötigte Wiener Diagnose-Eingaben fehlen" >&2
	exit 1
}

"$PYTHON" -m scripts.reverse_diagnose_boost_voronoi \
	--cache "$CACHE" \
	--aoi "$AOI" \
	--suspects "$SUSPECTS" \
	--out "$OUT" \
	"$@"
