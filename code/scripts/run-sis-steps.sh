#!/usr/bin/env bash
# Phasenweise SIS-Analyse: Quellen aus Downloads/read-only bzw. raw/, Ergebnisse in output/.
# Nutzt SIS statt FMZK+Kataster und lokale GIP2-EDGE-Achsen ohne Kreuzungsausschnitte.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT="$(cd .. && pwd -P)"
PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"
ROOT="${SIS_V2_ROOT:-$REPO_ROOT/work/wien}"
RAW="${SIS_V2_RAW_ROOT:-$REPO_ROOT/raw}"
PUBLISH="${SIS_V2_PUBLISH_DIR:-$REPO_ROOT/output}"
GRM_RAW="${SIS_V2_GRM_RAW_ROOT:-}"
SIS="${SIS_V2_SOURCE:-$RAW/SISBELAGOGD.json}"
GIP2="${GIP2_SOURCE:-/mnt/c/Users/peter/Downloads/gip_network_ogd.gpkg}"
SIS_DB="${SIS_V2_INDEX:-$ROOT/sis/sis.sqlite}"
STAGES=(sis aoi grid gip-index street partition trim qa grm-fetch grm-build measure pmtiles)
FROM=sis
UNTIL=pmtiles
WITH_GRM=1

usage() {
	cat <<'HELP'
bash code/scripts/run-sis-steps.sh [--from PHASE] [--until PHASE] [--no-grm]

Phasen: sis aoi grid gip-index street partition trim qa grm-fetch grm-build measure pmtiles

Optionale Umgebung:
  SIS_V2_SOURCE: lokale SIS-Datei (Standard: raw/SISBELAGOGD.json)
  SIS_V2_INDEX: optionaler zentraler SIS-SQLite-Index (Wien)
  SIS_V2_ROOT: Arbeitsverzeichnis (Standard: <Repo>/work/wien)
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
if [[ -L "$ROOT" ]]; then
	echo "Arbeitsverzeichnis ist Symlink: $ROOT" >&2
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
	mkdir -p "$ROOT"
fi

for ((i=start;i<=end;i++)); do
	step="${STAGES[$i]}"
	echo "== SIS V2: $step =="
	case "$step" in
		sis)
			if [[ ! -e "$ROOT/sis/sis.sqlite" ]]; then
				[[ -f "$SIS" ]] || { echo "SIS-Datei fehlt: $SIS" >&2; exit 1; }
				"$PYTHON" -m scripts.sis_belagsflaechen --source-file "$SIS" --out-dir "$ROOT/sis"
			fi;;
		aoi)
			[[ -e "$ROOT/aoi.geojson" ]] || "$PYTHON" -m scripts.sis_v2_aoi \
				--sis-db "$SIS_DB" --out "$ROOT/aoi.geojson";;
		grid)
			[[ -e "$ROOT/raster.json" ]] || "$PYTHON" -m scripts.wienwide_grid \
				--aoi "$ROOT/aoi.geojson" --tile-m "${SIS_V2_TILE_M:-1000}" --halo-m 75 --out "$ROOT/raster.json";;
		gip-index)
			[[ -f "$GIP2" ]] || { echo "GIP2-Datei fehlt: $GIP2" >&2; exit 1; }
			[[ -e "$ROOT/gip.sqlite" ]] || "$PYTHON" -m scripts.sis_gip2 \
				--source "$GIP2" --manifest "$ROOT/raster.json" --out "$ROOT/gip.sqlite";;
		street)
			"$PYTHON" -m scripts.sis_v2_street \
				--manifest "$ROOT/raster.json" --sis-db "$SIS_DB" \
				--out-root "$ROOT/strassenraum";;
		partition)
			"$PYTHON" -m scripts.wienwide_partition \
				--manifest "$ROOT/raster.json" --gip-index "$ROOT/gip.sqlite" \
				--street-root "$ROOT/strassenraum" --out "$ROOT/aufteilung_roh.sqlite" \
				--all-fow --no-junctions --gip2-local;;
		trim)
			[[ -e "$ROOT/aufteilung.sqlite" ]] || "$PYTHON" -m scripts.sis_v2_trim \
				--gip-index "$ROOT/gip.sqlite" \
				--partition-db "$ROOT/aufteilung_roh.sqlite" \
				--out "$ROOT/aufteilung.sqlite";;
		qa)
			[[ -e "$ROOT/qa.gpkg" ]] || "$PYTHON" -m scripts.wienwide_qa_gpkg \
				--manifest "$ROOT/raster.json" --gip-index "$ROOT/gip.sqlite" \
				--street-root "$ROOT/strassenraum" \
				--partition-db "$ROOT/aufteilung.sqlite" --out "$ROOT/qa.gpkg";;
		grm-fetch)
			if ((WITH_GRM)); then
				grm_args=()
				[[ -n "$GRM_RAW" ]] && grm_args=(--raw-root "$GRM_RAW")
				"$PYTHON" -m scripts.wienwide_grm2023 fetch \
					--manifest "$ROOT/raster.json" --root "$ROOT/grm2023" "${grm_args[@]}"
			fi;;
		grm-build)
			if ((WITH_GRM)); then
				grm_args=()
				[[ -n "$GRM_RAW" ]] && grm_args=(--raw-root "$GRM_RAW")
				"$PYTHON" -m scripts.wienwide_grm2023 build \
					--manifest "$ROOT/raster.json" --root "$ROOT/grm2023" "${grm_args[@]}"
			fi;;
		pmtiles)
			geojson="$ROOT/ergebnisse/gip_abschnitte.geojson"
			archive="$ROOT/gartenstrassen_sis_v2.pmtiles"
			if [[ -n "$PUBLISH" ]]; then
				geojson="$PUBLISH/gip_abschnitte.geojson"
				archive="$PUBLISH/gartenstrassen.pmtiles"
				mkdir -p "$PUBLISH"
			fi
			[[ -f "$geojson" ]] || { echo "GeoJSON-Ausgabe fehlt: $geojson" >&2; exit 1; }
			"$PYTHON" -m scripts.sis_v2_pmtiles \
				--geojson "$geojson" --out "$archive" \
				--min-area-m2 100 --replace;;
		measure)
			args=()
			if ((WITH_GRM)); then
				args=(--grm-root "$ROOT/grm2023")
				[[ -n "$GRM_RAW" ]] && args+=(--grm-raw-root "$GRM_RAW")
			fi
			"$PYTHON" -m scripts.sis_v2_measure \
				--manifest "$ROOT/raster.json" --gip-index "$ROOT/gip.sqlite" \
				--sis-db "$SIS_DB" --street-root "$ROOT/strassenraum" \
				--partition-db "$ROOT/aufteilung.sqlite" --out-dir "$ROOT/ergebnisse" "${args[@]}"
			if [[ -n "$PUBLISH" ]]; then
				mkdir -p "$PUBLISH"
				for name in gip_abschnitte.geojson gip_abschnitte.csv bericht.json; do
					[[ ! -L "$PUBLISH/$name" ]] || { echo "Symlink in Ausgabe: $name" >&2; exit 1; }
					cp -- "$ROOT/ergebnisse/$name" "$PUBLISH/$name.tmp"
					mv -f -- "$PUBLISH/$name.tmp" "$PUBLISH/$name"
				done
			fi;;
	esac
done
