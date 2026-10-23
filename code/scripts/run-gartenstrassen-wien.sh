#!/usr/bin/env bash
# Wiener Gesamtpipeline: vorbereitete SIS/GRM-Daten -> CGAL/SIS -> Kennzahlen.
# --from allows resuming without recomputing expensive earlier phases.
set -euo pipefail

cd "$(dirname "$0")/../.."
REPO="$PWD"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
CACHE="$REPO/cache/wien/linear_use_original.sqlite"
SIS_DB="${SIS_V2_INDEX:-$REPO/cache/sis-wien.sqlite}"
DATA="${SIS_V2_CACHE_WIEN:-$REPO/cache/wien}"
RAW="${SIS_V2_RAW_ROOT:-$REPO/raw}"
GRM_RAW="${SIS_V2_GRM_RAW_ROOT:-$RAW/grm2023}"
SIS_OUTPUT="$REPO/output/cgal_native_faces_sis_wien.geojson"
FINAL_OUTPUT="${GARTENSTRASSEN_FINAL_OUTPUT:-$REPO/output/cgal_native_faces_sis_grm_wien.geojson}"
STAGES=(prepare cgal stats)
FROM=prepare
UNTIL=stats
REPLACE_STATS=0

usage() {
	cat <<'HELP'
bash code/scripts/run-gartenstrassen-wien.sh [--from PHASE] [--until PHASE] [--replace-stats]

Phases:
  prepare  SIS index, street-space and GRM2023 cache preparation
  cgal     LINEAR_USE -> CGAL -> TURN_USE -> SIS GeoJSON
  stats    SIS ground + GRM2023 canopy + overlap statistics

Existing SIS GeoJSON and complete SIS/GRM caches:
  bash code/scripts/run-gartenstrassen-wien.sh --from stats

Options:
  --from PHASE      Resume at phase (inclusive)
  --until PHASE     Stop after phase (inclusive)
  --replace-stats   Explicitly replace an existing statistics output
  -h, --help        Show this help

The final statistics GeoJSON is separate from the SIS geometry source.
No PMTiles export is run by this script.
HELP
}

while (($#)); do
	case "$1" in
		--from|--until)
			(($# >= 2)) || { echo "Missing phase after $1" >&2; exit 2; }
			if [[ "$1" == --from ]]; then FROM="$2"; else UNTIL="$2"; fi
			shift 2;;
		--replace-stats) REPLACE_STATS=1; shift;;
		-h|--help) usage; exit 0;;
		*) echo "Unknown option: $1" >&2; usage >&2; exit 2;;
	esac
done

start=-1
end=-1
for i in "${!STAGES[@]}"; do
	[[ "${STAGES[$i]}" == "$FROM" ]] && start=$i
	[[ "${STAGES[$i]}" == "$UNTIL" ]] && end=$i
done
if ((start < 0 || end < start)); then
	echo "Invalid phase range: $FROM -> $UNTIL" >&2
	exit 2
fi

[[ -x "$PYTHON" ]] || { echo "Python missing: $PYTHON" >&2; exit 1; }
[[ ! -L "$REPO/output" && ! -L "$REPO/cache" ]] || {
	echo "output/ and cache/ must not be symlinks" >&2; exit 1;
}
mkdir -p "$REPO/output"

for ((i=start;i<=end;i++)); do
	stage="${STAGES[$i]}"
	echo "== Gartenstraßen Wien: $stage =="
	case "$stage" in
		prepare)
			bash "$REPO/code/scripts/run-sis-v2-wien.sh";;
		cgal)
			if [[ ! -f "$CACHE" ]]; then
				if [[ -e "$REPO/output/linear_use_original.geojson" ]]; then
					echo "Original GeoJSON present but LINEAR_USE SQLite missing" >&2
					exit 1
				fi
				bash "$REPO/code/scripts/run-linear-use-wien.sh"
			fi
			bash "$REPO/code/scripts/run-cgal-native-faces-pre-sis-wien.sh";;
		stats)
			[[ -s "$SIS_OUTPUT" ]] || {
				echo "Completed SIS GeoJSON missing: $SIS_OUTPUT" >&2
				echo "First run --from cgal --until cgal or provide the finished file" >&2
				exit 1
			}
			[[ -s "$DATA/raster.json" && -f "$SIS_DB" ]] || {
				echo "SIS index or GRM tile manifest missing; run prepare" >&2
				exit 1
			}
			args=(
				--source "$SIS_OUTPUT"
				--sis-db "$SIS_DB"
				--manifest "$DATA/raster.json"
				--grm-root "$DATA"
				--raw-root "$GRM_RAW"
				--out "$FINAL_OUTPUT"
			)
			((REPLACE_STATS == 0)) || args+=(--replace-existing)
			(cd "$REPO/code" && "$PYTHON" -m scripts.analyze_cgal_sis_grm "${args[@]}");;
	esac
	echo "== $stage completed =="
done
