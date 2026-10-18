#!/usr/bin/env bash
# Wienweite Gartenstraßen-Bestandsanalyse mit geprüften Caches und 100-m²-Ausgabe.
# Die Originale und sämtliche QA-Flächen bleiben unverändert.
set -euo pipefail

# V0 ist historisch; alte data/processed/-Strukturen nicht erneut erzeugen.
if [[ "${KS_ALLOW_LEGACY_V0:-0}" != "1" ]]; then
	echo "Historische V0-Pipeline deaktiviert. Wien-SIS-V2: scripts/run-sis-v2-wien.sh" >&2
	echo "Nur zur Reproduktion alter Methoden: KS_ALLOW_LEGACY_V0=1 setzen." >&2
	exit 2
fi

cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-.venv/bin/python}"
FMZK="${FMZK_SOURCE:-data/raw/FMZK_WIEN_GP.gpkg}"
ROOT="${WIEN_ROOT:-data/processed/wienweit/wien}"
AOI_DIR="${WIEN_AOI_DIR:-data/raw/bezirke-wien}"
AOI="$AOI_DIR/wien.geojson"
MANIFEST="$ROOT/raster.json"
GIP_FRAGMENTS="$ROOT/gip_fragmente"
GIP_INDEX="$ROOT/gip.sqlite"
INPUTS="$ROOT/eingaben"
STREET="$ROOT/strassenraum"
PARTITION="$ROOT/aufteilung.sqlite"
QA="$ROOT/wien_qa.gpkg"
GRM="$ROOT/grm2023"
MEASURED="$ROOT/begruenung_grm"
PUBLISHED="$ROOT/veroeffentlichung_100m2"
STAGES=(aoi grid gip-fetch gip-index inputs street partition qa grm-fetch grm-build measure export benchmark)
FROM=aoi
UNTIL=benchmark

usage() {
	cat <<'HELP'
Wienweite Gartenstraßenanalyse (lokal aus dem Repository-Verzeichnis).

  bash scripts/run-wien-gartenstrassen.sh [--from PHASE] [--until PHASE] [--fmzk DATEI]

Phasen:
  aoi grid gip-fetch gip-index inputs street partition qa
  grm-fetch grm-build measure export benchmark

Alle Phasen: Standard. Mit --until zunächst nur einen Teil durchführen;
mit --from nach erfolgreichen Phasen oder einem Fehler fortsetzen.
Vorhandene Ergebnisse werden nicht überschrieben; für neue Methoden
bitte einen anderen WIEN_ROOT wählen. Alle Eingaben bleiben lokal.
Umgebungsvariablen: PYTHON, FMZK_SOURCE, WIEN_ROOT, WIEN_AOI_DIR.
HELP
}

while (($#)); do
	case "$1" in
		--from|--until|--fmzk)
			if (($# < 2)); then echo "Fehlender Wert für $1" >&2; exit 2; fi
			case "$1" in
				--from) FROM="$2";;
				--until) UNTIL="$2";;
				--fmzk) FMZK="$2";;
			esac
			shift 2;;
		-h|--help) usage; exit 0;;
		*) echo "Unbekanntes Argument: $1" >&2; usage >&2; exit 2;;
	esac
done

index_of() {
	local i
	for i in "${!STAGES[@]}"; do
		if [[ "${STAGES[$i]}" == "$1" ]]; then echo "$i"; return 0; fi
	done
	return 1
}
if ! START=$(index_of "$FROM") || ! END=$(index_of "$UNTIL") || ((START > END)); then
	echo "Ungültige Phasenauswahl: $FROM bis $UNTIL" >&2
	exit 2
fi
if [[ ! -x "$PYTHON" ]]; then
	echo "Python-Venv fehlt: $PYTHON (siehe README/requirements-analysis.txt)" >&2
	exit 1
fi

for ((i=START;i<=END;i++)); do
	stage="${STAGES[$i]}"
	printf '\n== Wien: %s ==\n' "$stage"
	case "$stage" in
		aoi)
			if [[ -e "$AOI" ]]; then
				echo "Bestehende Wien-AOI: $AOI"
			else
				"$PYTHON" -m scripts.wienwide_aoi --bezirke --wien --out-dir "$AOI_DIR"
			fi;;
		grid)
			if [[ -e "$MANIFEST" ]]; then
				echo "Bestehendes Rastermanifest: $MANIFEST"
			else
				"$PYTHON" -m scripts.wienwide_grid --aoi "$AOI" \
					--tile-m 1000 --halo-m 75 --out "$MANIFEST"
			fi;;
		gip-fetch)
			"$PYTHON" -m scripts.wienwide_gip fetch \
				--manifest "$MANIFEST" --out-dir "$GIP_FRAGMENTS";;
		gip-index)
			if [[ ! -e "$GIP_INDEX" ]]; then
				"$PYTHON" -m scripts.wienwide_gip index \
					--manifest "$MANIFEST" --fragments "$GIP_FRAGMENTS" --out "$GIP_INDEX"
			else
				echo "Bestehender GIP-Index: $GIP_INDEX"
			fi;;
		inputs)
			if [[ ! -f "$FMZK" ]]; then
				echo "Lokales FMZK-Original fehlt: $FMZK" >&2; exit 1
			fi
			"$PYTHON" -m scripts.wienwide_street fetch-inputs \
				--manifest "$MANIFEST" --input-root "$INPUTS" \
				--fmzk-source "$FMZK" --kataster-cache data/cache/kataster \
				--max-parcels 2500;;
		street)
			"$PYTHON" -m scripts.wienwide_street build \
				--manifest "$MANIFEST" --input-root "$INPUTS" \
				--out-root "$STREET" --kataster-cache data/cache/kataster;;
		partition)
			"$PYTHON" -m scripts.wienwide_partition \
				--manifest "$MANIFEST" --gip-index "$GIP_INDEX" \
				--street-root "$STREET" --out "$PARTITION";;
		qa)
			if [[ ! -e "$QA" ]]; then
				"$PYTHON" -m scripts.wienwide_qa_gpkg \
					--manifest "$MANIFEST" --gip-index "$GIP_INDEX" \
					--street-root "$STREET" --partition-db "$PARTITION" --out "$QA"
			else
				echo "Bestehendes QA-GeoPackage: $QA"
			fi;;
		grm-fetch)
			"$PYTHON" -m scripts.wienwide_grm2023 fetch \
				--manifest "$MANIFEST" --root "$GRM" --pause-s 0.5;;
		grm-build)
			"$PYTHON" -m scripts.wienwide_grm2023 build \
				--manifest "$MANIFEST" --root "$GRM";;
		measure)
			if [[ ! -e "$MEASURED" ]]; then
				"$PYTHON" -m scripts.wienwide_gip_greening \
					--manifest "$MANIFEST" --gip-index "$GIP_INDEX" \
					--street-root "$STREET" --input-root "$INPUTS" \
					--partition-db "$PARTITION" --qa-gpkg "$QA" \
					--grm-root "$GRM" --out-dir "$MEASURED"
			else
				echo "Bestehende Gesamtmessung: $MEASURED"
			fi;;
		export)
			if [[ ! -e "$PUBLISHED" ]]; then
				"$PYTHON" -m scripts.wienwide_result_export \
					--csv "$MEASURED/gip_abschnitte_begruenung.csv" \
					--gpkg "$MEASURED/gip_abschnitte_begruenung.gpkg" \
					--min-area-m2 100 --out-dir "$PUBLISHED"
			else
				echo "Bereits veröffentlichte 100-m²-Ausgabe: $PUBLISHED"
			fi;;
		benchmark)
			if [[ ! -e "$ROOT/benchmark.json" ]]; then
				"$PYTHON" -m scripts.wienwide_benchmark \
					--manifest "$MANIFEST" --inputs "$INPUTS" \
					--gip-fragments "$GIP_FRAGMENTS" --street-root "$STREET" \
					--gip-index "$GIP_INDEX" --partition-db "$PARTITION" \
					--out "$ROOT/benchmark.json"
			else
				echo "Bestehender Benchmark: $ROOT/benchmark.json"
			fi;;
	esac
done

echo "Wien-Phasen $FROM bis $UNTIL abgeschlossen."
