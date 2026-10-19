#!/usr/bin/env bash
# Dauerhafte Vorbereitung der Wiener SIS- und GRM-Daten.
# Keine GIP-Achsen, keine Abschnittszuordnung, keine Kreuzungsausschnitte.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT="$(cd .. && pwd -P)"
PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"
DATA="${SIS_V2_CACHE_WIEN:-$REPO_ROOT/cache/wien}"
RAW="${SIS_V2_RAW_ROOT:-$REPO_ROOT/raw}"
GRM_RAW="${SIS_V2_GRM_RAW_ROOT:-}"
SIS_DB="${SIS_V2_INDEX:-$REPO_ROOT/cache/sis-wien.sqlite}"
STAGES=(aoi grid street grm-fetch grm-build)
FROM=aoi
UNTIL=grm-build

usage() {
	cat <<'HELP'
bash code/scripts/run-sis-steps.sh [--from PHASE] [--until PHASE]

Phasen: aoi grid street grm-fetch grm-build

Optionale Umgebung:
  SIS_V2_INDEX: dauerhafter Wiener SIS-SQLite-Index
  SIS_V2_CACHE_WIEN: dauerhafte aufbereitete GIS-Daten (<Repo>/cache/wien)
  SIS_V2_RAW_ROOT: Rohdatenordner (Standard: raw/)
  SIS_V2_GRM_RAW_ROOT: heruntergeladene GRM-PNGs
  PYTHON: Python aus requirements-analysis.txt

Dieser Ablauf bereitet ausschließlich SIS-Straßenraum und GRM2023 vor.
Es gibt bewusst keine GIP-, Voronoi-, Abschnitts-, Kreuzungs- oder PMTiles-Phase.
HELP
}

while (($#)); do
	case "$1" in
		--from) FROM="$2"; shift 2;;
		--until) UNTIL="$2"; shift 2;;
		-h|--help) usage; exit 0;;
		*) echo "Ungültige Option: $1" >&2; exit 2;;
	esac
done

[[ -x "$PYTHON" ]] || { echo "Python-Venv fehlt: $PYTHON" >&2; exit 1; }
[[ ! -L "$DATA" ]] || { echo "Cacheverzeichnis ist Symlink: $DATA" >&2; exit 1; }

start=-1
end=-1
for i in "${!STAGES[@]}"; do
	[[ "${STAGES[$i]}" == "$FROM" ]] && start=$i
	[[ "${STAGES[$i]}" == "$UNTIL" ]] && end=$i
done
if ((start < 0 || end < start)); then
	echo "Ungültige Phasenfolge" >&2
	exit 2
fi
mkdir -p "$DATA"

for ((i=start;i<=end;i++)); do
	step="${STAGES[$i]}"
	step_start=$SECONDS
	echo "== SIS/GRM Vorbereitung: $step =="
	case "$step" in
		aoi)
			[[ -e "$DATA/aoi.geojson" ]] || "$PYTHON" -m scripts.sis_v2_aoi \
				--sis-db "$SIS_DB" --out "$DATA/aoi.geojson";;
		grid)
			[[ -e "$DATA/raster.json" ]] || "$PYTHON" -m scripts.wienwide_grid \
				--aoi "$DATA/aoi.geojson" --tile-m "${SIS_V2_TILE_M:-1000}" \
				--halo-m 75 --out "$DATA/raster.json"
			"$PYTHON" -m scripts.verify_wien_cache \
				--cache "$DATA" --tile-m "${SIS_V2_TILE_M:-1000}";;
		street)
			"$PYTHON" -m scripts.sis_v2_street \
				--manifest "$DATA/raster.json" --sis-db "$SIS_DB" \
				--out-root "$DATA/strassenraum";;
		grm-fetch)
			grm_args=()
			[[ -n "$GRM_RAW" ]] && grm_args=(--raw-root "$GRM_RAW")
			"$PYTHON" -m scripts.wienwide_grm2023 fetch \
				--manifest "$DATA/raster.json" --root "$DATA" "${grm_args[@]}";;
		grm-build)
			grm_args=()
			[[ -n "$GRM_RAW" ]] && grm_args=(--raw-root "$GRM_RAW")
			"$PYTHON" -m scripts.wienwide_grm2023 build \
				--manifest "$DATA/raster.json" --root "$DATA" "${grm_args[@]}";;
	esac
	echo "== $step abgeschlossen in $((SECONDS-step_start)) s =="
done
