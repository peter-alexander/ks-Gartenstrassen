#!/usr/bin/env bash
# SIS-basierte V2-Pilotanalyse – vollständig getrennter Arbeitsbereich.
# Nutzt SIS statt FMZK+Kataster, GIP V0-Kreuzungsregel bis zur fachlichen Prüfung.
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-.venv/bin/python}"
ROOT="${SIS_V2_ROOT:-data/processed/sis-v2-run}"
SIS="${SIS_V2_SOURCE:-}"
STAGES=(sis aoi grid gip-fetch gip-index street partition qa grm-fetch grm-build measure)
FROM=sis
UNTIL=measure
WITH_GRM=1

usage() {
	cat <<'HELP'
bash scripts/run-sis-v2-pilot.sh [--from PHASE] [--until PHASE] [--no-grm]

Phasen: sis aoi grid gip-fetch gip-index street partition qa grm-fetch grm-build measure

Optionale Umgebung:
  SIS_V2_SOURCE: lokal vorhandenes SISBELAGOGD.json; sonst Download Testquelle
  SIS_V2_ROOT: separates Ausgabeverzeichnis (kein V0-Pfad!)
  PYTHON: Python aus requirements-analysis.txt

V2 nutzt für Straßenflächen ausschließlich SIS. GIP-Kanten und GRM 2023
werden wie bisher eingelesen, die alte V0-Kreuzungsregel bleibt vorläufig.
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
case "$ROOT" in
	data/processed/wienweit/wien|data/processed/wienweit/wien/*)
		echo "V0-Ausgabepfade dürfen nicht wiederverwendet werden" >&2; exit 1;;
esac
start=-1
end=-1
for i in "${!STAGES[@]}"; do
	[[ "${STAGES[$i]}" == "$FROM" ]] && start=$i
	[[ "${STAGES[$i]}" == "$UNTIL" ]] && end=$i
done
if ((start < 0 || end < start)); then
	echo "Ungültige Phasenfolge" >&2; exit 2
fi
mkdir -p "$ROOT"

for ((i=start;i<=end;i++)); do
	step="${STAGES[$i]}"
	echo "== SIS V2: $step =="
	case "$step" in
		sis)
			if [[ ! -e "$ROOT/sis/sis.sqlite" ]]; then
				if [[ -n "$SIS" ]]; then
					"$PYTHON" -m scripts.sis_belagsflaechen --source-file "$SIS" --out-dir "$ROOT/sis"
				else
					"$PYTHON" -m scripts.sis_belagsflaechen --out-dir "$ROOT/sis"
				fi
			fi;;
		aoi)
			[[ -e "$ROOT/aoi.geojson" ]] || "$PYTHON" -m scripts.sis_v2_aoi \
				--sis-db "$ROOT/sis/sis.sqlite" --out "$ROOT/aoi.geojson";;
		grid)
			[[ -e "$ROOT/raster.json" ]] || "$PYTHON" -m scripts.wienwide_grid \
				--aoi "$ROOT/aoi.geojson" --tile-m 250 --halo-m 75 --out "$ROOT/raster.json";;
		gip-fetch)
			"$PYTHON" -m scripts.wienwide_gip fetch \
				--manifest "$ROOT/raster.json" --out-dir "$ROOT/gip_fragmente";;
		gip-index)
			[[ -e "$ROOT/gip.sqlite" ]] || "$PYTHON" -m scripts.wienwide_gip index \
				--manifest "$ROOT/raster.json" --fragments "$ROOT/gip_fragmente" --out "$ROOT/gip.sqlite";;
		street)
			"$PYTHON" -m scripts.sis_v2_street \
				--manifest "$ROOT/raster.json" --sis-db "$ROOT/sis/sis.sqlite" \
				--out-root "$ROOT/strassenraum";;
		partition)
			"$PYTHON" -m scripts.wienwide_partition \
				--manifest "$ROOT/raster.json" --gip-index "$ROOT/gip.sqlite" \
				--street-root "$ROOT/strassenraum" --out "$ROOT/aufteilung.sqlite";;
		qa)
			[[ -e "$ROOT/qa.gpkg" ]] || "$PYTHON" -m scripts.wienwide_qa_gpkg \
				--manifest "$ROOT/raster.json" --gip-index "$ROOT/gip.sqlite" \
				--street-root "$ROOT/strassenraum" \
				--partition-db "$ROOT/aufteilung.sqlite" --out "$ROOT/qa.gpkg";;
		grm-fetch)
			if ((WITH_GRM)); then
				"$PYTHON" -m scripts.wienwide_grm2023 fetch \
					--manifest "$ROOT/raster.json" --root "$ROOT/grm2023"
			fi;;
		grm-build)
			if ((WITH_GRM)); then
				"$PYTHON" -m scripts.wienwide_grm2023 build \
					--manifest "$ROOT/raster.json" --root "$ROOT/grm2023"
			fi;;
		measure)
			args=()
			if ((WITH_GRM)); then args=(--grm-root "$ROOT/grm2023"); fi
			"$PYTHON" -m scripts.sis_v2_measure \
				--manifest "$ROOT/raster.json" --gip-index "$ROOT/gip.sqlite" \
				--sis-db "$ROOT/sis/sis.sqlite" --street-root "$ROOT/strassenraum" \
				--partition-db "$ROOT/aufteilung.sqlite" --out-dir "$ROOT/ergebnisse" "${args[@]}";;
	esac
done
