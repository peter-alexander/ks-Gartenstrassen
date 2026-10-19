#!/usr/bin/env bash
# Phasenweise SIS-Analyse: Quellen aus Downloads/read-only bzw. raw/, Ergebnisse in output/.
# Nutzt SIS statt FMZK+Kataster und lokale GIP2-EDGE-Achsen ohne Kreuzungsausschnitte.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT="$(cd .. && pwd -P)"
PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"
ROOT="${SIS_V2_ROOT:-$REPO_ROOT/work/wien}"
DATA="${SIS_V2_CACHE_WIEN:-$REPO_ROOT/cache/wien}"
RAW="${SIS_V2_RAW_ROOT:-$REPO_ROOT/raw}"
PUBLISH="${SIS_V2_PUBLISH_DIR:-$REPO_ROOT/output}"
GRM_RAW="${SIS_V2_GRM_RAW_ROOT:-}"
SIS="${SIS_V2_SOURCE:-$RAW/SISBELAGOGD.json}"
GIP2="${GIP2_SOURCE:-/mnt/c/Users/peter/Downloads/gip_network_ogd.gpkg}"
SIS_DB="${SIS_V2_INDEX:-$REPO_ROOT/cache/sis-wien.sqlite}"
STAGES=(sis aoi grid gip-index gip-merge street partition trim qa grm-fetch grm-build measure pmtiles)
FROM=sis
UNTIL=pmtiles
WITH_GRM=1

usage() {
	cat <<'HELP'
bash code/scripts/run-sis-steps.sh [--from PHASE] [--until PHASE] [--no-grm]

Phasen: sis aoi grid gip-index gip-merge street partition trim qa grm-fetch grm-build measure pmtiles

Optionale Umgebung:
  SIS_V2_SOURCE: lokale SIS-Datei (Standard: raw/SISBELAGOGD.json)
  SIS_V2_INDEX: optionaler zentraler SIS-SQLite-Index (Wien)
  SIS_V2_ROOT: temporäre Messdaten (Standard: <Repo>/work/wien)
  SIS_V2_CACHE_WIEN: dauerhafte GIS-Zwischendaten (<Repo>/cache/wien)
  SIS_V2_RAW_ROOT: Rohdatenordner (Standard: raw/)
  SIS_V2_PUBLISH_DIR: dauerhafte Ausgaben (z. B. output/)
  SIS_V2_GRM_RAW_ROOT: heruntergeladene GRM-PNGs
  GIP2_SOURCE: schreibgeschützte Originaldatei in Windows Downloads
  PYTHON: Python aus requirements-analysis.txt

V2 nutzt SIS und ausschließlich lokale GIP2 EDGE/NODE/TURN_USE.
In diesem Versuch werden keine Kreuzungsflächen ausgeschnitten.
HELP
}

while (($#)); do
	case "$1" in
		--from) FROM="$2"; shift 2;;
		--until) UNTIL="$2"; shift 2;;
		--no-grm) WITH_GRM=0; shift;;
		-h|--help) usage; exit 0;;
		*) echo "Ungültige Option: $1" >&2; exit 2;;
	esac
done

if [[ ! -x "$PYTHON" ]]; then
	echo "Python-Venv fehlt: $PYTHON" >&2; exit 1
fi
# Der bisherige automatische rm -rf des Pilotverzeichnisses ist deaktiviert.
if [[ -L "$ROOT" || -L "$DATA" ]]; then
	echo "Arbeits- oder Cacheverzeichnis ist Symlink: $ROOT / $DATA" >&2
	exit 1
fi
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
if [[ "$FROM" != "pmtiles" ]]; then
	mkdir -p "$ROOT" "$DATA"
fi

for ((i=start;i<=end;i++)); do
	step="${STAGES[$i]}"
	step_start=$SECONDS
	echo "== SIS V2: $step =="
	case "$step" in
		sis)
			if [[ ! -e "$ROOT/sis/sis.sqlite" ]]; then
				[[ -f "$SIS" ]] || { echo "SIS-Datei fehlt: $SIS" >&2; exit 1; }
				"$PYTHON" -m scripts.sis_belagsflaechen --source-file "$SIS" --out-dir "$ROOT/sis"
			fi;;
		aoi)
			[[ -e "$DATA/aoi.geojson" ]] || "$PYTHON" -m scripts.sis_v2_aoi \
				--sis-db "$SIS_DB" --out "$DATA/aoi.geojson";;
		grid)
			[[ -e "$DATA/raster.json" ]] || "$PYTHON" -m scripts.wienwide_grid \
				--aoi "$DATA/aoi.geojson" --tile-m "${SIS_V2_TILE_M:-1000}" --halo-m 75 --out "$DATA/raster.json";;
		gip-index)
			[[ -f "$GIP2" ]] || { echo "GIP2-Datei fehlt: $GIP2" >&2; exit 1; }
			[[ -e "$DATA/gip.sqlite" ]] || "$PYTHON" -m scripts.sis_gip2 \
				--source "$GIP2" --manifest "$DATA/raster.json" --out "$DATA/gip.sqlite";;
		gip-merge)
			"$PYTHON" -m scripts.merge_parallel_gip \
				--source-index "$DATA/gip.sqlite" --out "$DATA/gip_merged.sqlite" \
				--reuse;;
		street)
			"$PYTHON" -m scripts.sis_v2_street \
				--manifest "$DATA/raster.json" --sis-db "$SIS_DB" \
				--out-root "$DATA/strassenraum";;
		partition)
			"$PYTHON" -m scripts.wienwide_partition \
				--manifest "$DATA/raster.json" --gip-index "$DATA/gip_merged.sqlite" \
				--street-root "$DATA/strassenraum" --out "$DATA/aufteilung_roh.sqlite" \
				--all-fow --no-junctions --gip2-local;;
		trim)
			[[ -e "$DATA/aufteilung.sqlite" ]] || "$PYTHON" -m scripts.sis_v2_trim \
				--gip-index "$DATA/gip_merged.sqlite" \
				--partition-db "$DATA/aufteilung_roh.sqlite" \
				--out "$DATA/aufteilung.sqlite";;
		qa)
			[[ -e "$DATA/qa.gpkg" ]] || "$PYTHON" -m scripts.wienwide_qa_gpkg \
				--manifest "$DATA/raster.json" --gip-index "$DATA/gip_merged.sqlite" \
				--street-root "$DATA/strassenraum" \
				--partition-db "$DATA/aufteilung.sqlite" --out "$DATA/qa.gpkg";;
		grm-fetch)
			if ((WITH_GRM)); then
				grm_args=()
				[[ -n "$GRM_RAW" ]] && grm_args=(--raw-root "$GRM_RAW")
				"$PYTHON" -m scripts.wienwide_grm2023 fetch \
					--manifest "$DATA/raster.json" --root "$DATA" "${grm_args[@]}"
			fi;;
		grm-build)
			if ((WITH_GRM)); then
				grm_args=()
				[[ -n "$GRM_RAW" ]] && grm_args=(--raw-root "$GRM_RAW")
				"$PYTHON" -m scripts.wienwide_grm2023 build \
					--manifest "$DATA/raster.json" --root "$DATA" "${grm_args[@]}"
			fi;;
		pmtiles)
			# Kein Mischen alter und neuer Veröffentlichungsdateien.
			# Der Zwischenordner liegt nur während des Exports unter output/.
			source="$ROOT/ergebnisse"
			[[ -f "$source/bericht.json" ]] || source="$PUBLISH"
			group_args=()
			[[ -f "$DATA/gip_merged.sqlite" ]] && group_args=(
				--gip-index "$DATA/gip_merged.sqlite")
			"$PYTHON" -m scripts.publish_wien \
				--source "$source" --out "$PUBLISH" "${group_args[@]}";;
		measure)
			args=()
			if ((WITH_GRM)); then
				args=(--grm-root "$DATA")
				[[ -n "$GRM_RAW" ]] && args+=(--grm-raw-root "$GRM_RAW")
			fi
			"$PYTHON" -m scripts.sis_v2_measure \
				--manifest "$DATA/raster.json" --gip-index "$DATA/gip_merged.sqlite" \
				--sis-db "$SIS_DB" --street-root "$DATA/strassenraum" \
				--partition-db "$DATA/aufteilung.sqlite" --out-dir "$ROOT/ergebnisse" \
				--resume "${args[@]}";;
	esac
	echo "== $step abgeschlossen in $((SECONDS-step_start)) s =="
done
