#!/usr/bin/env bash
# Original LINEAR_USE -> CGAL -> TURN_USE -> edge_id -> 250m² -> SIS overlay.
# Native preview is a reusable cache, NOT a separately published result.
set -euo pipefail

cd "$(dirname "$0")/../.."
REPO="$PWD"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
CACHE="$REPO/cache/wien/linear_use_original.sqlite"
AOI="$REPO/cache/wien/aoi.geojson"
BUILD="$REPO/build/cgal"
BIN="$BUILD/cgal_voronoi_faces"
PREVIEW_BASE="$REPO/output/cgal_native_faces_inner_points_pre_sis_wien.geojson"
OUT="$REPO/output/cgal_native_faces_sis_wien.geojson"
SIS_DB="${SIS_V2_INDEX:-$REPO/cache/sis-wien.sqlite}"
TURN_SOURCE="${GIP_NETWORK_SOURCE:-/mnt/c/Users/peter/Downloads/gip_network_ogd.gpkg}"

[[ -x "$PYTHON" ]] || { echo "Python fehlt: $PYTHON" >&2; exit 1; }
[[ -f "$CACHE" && -f "$AOI" ]] || {
	echo "Wiener Original-LINEAR_USE-Daten oder AOI fehlen" >&2; exit 1;
}
[[ ! -L "$REPO/output" ]] || { echo "output/ darf kein Symlink sein" >&2; exit 1; }
[[ ! -L "$OUT" ]] || {
	echo "SIS-Ausgabe darf kein Symlink sein: $OUT" >&2; exit 1;
}
command -v cmake >/dev/null || { echo "cmake fehlt" >&2; exit 1; }
cmake -S "$REPO/code/cgal" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD" --parallel 2

# Die strenge Face-Rekonstruktion ist noch nicht freigegeben.
# Zunächst die bekannte, selektierte Segment-/Punkt-Vorschau sicherstellen.
(cd "$REPO/code" && "$PYTHON" -m scripts.build_cgal_native_faces_pre_sis \
	--cache "$CACHE" \
	--aoi "$AOI" \
	--binary "$BIN" \
	--out "$PREVIEW_BASE" \
	--preview-only \
	"$@")

# --preview-only bleibt als explizite Diagnoseoption verfügbar.
for option in "$@"; do
	if [[ "$option" == "--preview-only" ]]; then
		exit 0
	fi
done

# Wenn der Wiener SIS-Index fehlt, lieber vor dem Dissolve abbrechen,
# statt irrtümlich ein ungeclipptes Endergebnis zu veröffentlichen.
[[ -f "$SIS_DB" && -r "$SIS_DB" ]] || {
	echo "SIS-Wien-Index fehlt: $SIS_DB" >&2
	echo "Zuerst bash code/scripts/run-sis-v2-wien.sh ausführen." >&2
	exit 1
}
# Gleiche TURN_USE-Kreuzungshüllen wie in der historischen GIP2-SIS-V2-
# Pipeline: pro NODE konvexe Hülle aller zugeordneten TURN_USE-Linien.
# Der Abzug erfolgt je Face vor der Vereinigung nach originaler edge_id.
[[ -f "$TURN_SOURCE" && -r "$TURN_SOURCE" ]] || {
	echo "GIP2-GeoPackage mit NODE/TURN_USE nicht lesbar: $TURN_SOURCE" >&2
	exit 1
}
# Intermediäres Pre-SIS-GeoJSON und Bericht bleiben TEMPORÄR.
# Das reguläre output/ erhält nur das fertige SIS-Ergebnis und Debug.
WORK="$(mktemp -d "$REPO/cache/wien/.cgal-sis-stage-XXXXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT
PREVIEW="$REPO/output/cgal_native_faces_inner_points_pre_sis_wien__preview.geojson"
PRE_SIS="$WORK/cgal_dissolved_before_sis.geojson"
DEBUG_STAGE="$WORK/debug_before_sis.geojson"
REPORT_STAGE="$WORK/dissolve_report.json"
DEBUG="$REPO/output/cgal_native_faces_inner_points_pre_sis_wien__dissolve_debug.geojson"

[[ ! -L "$DEBUG" ]] || { echo "Debug-Ausgabe darf kein Symlink sein: $DEBUG" >&2; exit 1; }

(cd "$REPO/code" && "$PYTHON" -m scripts.dissolve_cgal_preview \
	--preview "$PREVIEW" \
	--out "$PRE_SIS" \
	--debug "$DEBUG_STAGE" \
	--report "$REPORT_STAGE" \
	--turn-use-source "$TURN_SOURCE" \
	--aoi "$AOI")

# Nur die abschließend mit allen SIS-Belagsflächen geschnittenen
# Flächen veröffentlichen. Leere SIS-Schnitte erscheinen nicht.
(cd "$REPO/code" && "$PYTHON" -m scripts.clip_cgal_with_sis \
	--pre-sis "$PRE_SIS" \
	--sis-db "$SIS_DB" \
	--out "$OUT" \
	--replace-existing)

# Debug bleibt ausdrücklich VOR SIS: TURN_USE + 250-m²-Schlussstufe.
# Erst nach vollständig erfolgreichem SIS-Lauf ersetzen.
mv -f -- "$DEBUG_STAGE" "$DEBUG"

# Diese vor-SIS-Endergebnisse sind obsolet; die native CGAL-Vorschau
# bleibt als wiederverwendbarer Cache bestehen.
rm -f -- \
	"$REPO/output/cgal_native_faces_inner_points_pre_sis_wien.geojson" \
	"$REPO/output/cgal_native_faces_inner_points_pre_sis_wien__dissolve_report.json"

echo "SIS-Ausgabe: $OUT"
echo "Debug vor SIS: $DEBUG"
