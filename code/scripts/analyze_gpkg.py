#!/usr/bin/env python3
"""FMZK-Flächenstatistik direkt aus dem lokalen, ausgeschnittenen GeoPackage."""

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import sqlite3
import struct
from urllib.parse import quote

from shapely import from_wkb, make_valid, union_all
from shapely.geometry import MultiPolygon, Polygon
from shapely.validation import explain_validity

from scripts.extract_fmzk import gpkg_info, parse_bbox, projected_clip

DEFAULT_SOURCE = Path("data/processed/fmzk_test.gpkg")
DEFAULT_OUTPUT = Path("data/processed/analysis")
GEOPACKAGE_ENVELOPE_BYTES = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}


def decode_gpkg_geometry(blob, feature_id):
	"""GeoPackageBinary-Header entfernen; Geometrie im nativen CRS belassen."""
	if blob is None:
		raise ValueError(f"Feature {feature_id}: fehlende Geometrie")
	data = bytes(blob)
	if len(data) < 9 or data[:2] != b"GP":
		raise ValueError(f"Feature {feature_id}: ungültiger GeoPackageBinary-Header")
	if data[2] != 0:
		raise ValueError(f"Feature {feature_id}: nicht unterstützte GeoPackageBinary-Version {data[2]}")
	flags = data[3]
	envelope_type = (flags >> 1) & 0x07
	if envelope_type not in GEOPACKAGE_ENVELOPE_BYTES:
		raise ValueError(f"Feature {feature_id}: unbekannter Envelope-Typ {envelope_type}")
	if flags & 0x10:
		raise ValueError(f"Feature {feature_id}: leere GeoPackage-Geometrie")
	byte_order = "<" if (flags & 1) else ">"
	srs_id = struct.unpack(byte_order + "i", data[4:8])[0]
	if srs_id != 31256:
		raise ValueError(f"Feature {feature_id}: Geometrie-SRS {srs_id} statt EPSG:31256")
	offset = 8 + GEOPACKAGE_ENVELOPE_BYTES[envelope_type]
	if len(data) <= offset:
		raise ValueError(f"Feature {feature_id}: WKB-Teil fehlt")
	try:
		return from_wkb(data[offset:])
	except Exception as exc:
		raise ValueError(f"Feature {feature_id}: ungültige oder nicht unterstützte WKB-Geometrie: {exc}") from exc


def polygonal_part(geometry):
	if isinstance(geometry, (Polygon, MultiPolygon)):
		return geometry
	if geometry.geom_type == "GeometryCollection":
		parts = [part for geom in geometry.geoms if (part := polygonal_part(geom)) is not None and not part.is_empty]
		return union_all(parts) if parts else None
	return None


def analyze(source=DEFAULT_SOURCE, output_dir=DEFAULT_OUTPUT):
	source, output_dir = Path(source), Path(output_dir)
	if not source.is_file():
		raise FileNotFoundError(f"Ausgeschnittenes GeoPackage fehlt: {source}")
	metadata_path = source.with_suffix(".json")
	if not metadata_path.is_file():
		raise FileNotFoundError(f"Extraktionsmetadaten fehlen: {metadata_path}")
	metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
	if metadata.get("output_layer") != "fmzk" or metadata.get("output_srs") != "EPSG:31256":
		raise ValueError("Extraktionsmetadaten passen nicht zum erwarteten Layer fmzk / EPSG:31256")
	bbox = parse_bbox(",".join(map(str, metadata["bbox_lon_lat"])))
	clip_area = projected_clip(bbox)
	layer_info = gpkg_info(source, "fmzk")
	column = layer_info["geometry_column"]
	# Die Tabellen- und Spaltennamen kommen ausschließlich aus geprüfter GPKG-Metadatenstruktur.
	quoted_geom = '"' + column.replace('"', '""') + '"'
	db_uri = "file:" + quote(str(source.resolve()), safe="/") + "?mode=ro"
	categories = defaultdict(list)
	labels = defaultdict(Counter)
	geometry_types = Counter()
	repair_log = []
	total = 0
	outside_tolerance_count = 0
	max_outside_area = 0.0

	with sqlite3.connect(db_uri, uri=True) as conn:
		for fid, blob, code, label in conn.execute(
			f'SELECT "id", {quoted_geom}, "F_KLASSE", "F_KLASSE_TEXT" FROM "fmzk"'
		):
			total += 1
			if code is None:
				raise ValueError(f"Feature {fid}: F_KLASSE fehlt")
			geometry = decode_gpkg_geometry(blob, fid)
			geometry_types[geometry.geom_type] += 1
			if not geometry.is_valid:
				reason = explain_validity(geometry)
				geometry = polygonal_part(make_valid(geometry))
				if geometry is None or geometry.is_empty or not geometry.is_valid:
					raise ValueError(f"Feature {fid}: Geometrie nicht reparierbar: {reason}")
				repair_log.append({"id": fid, "f_klasse": code, "reason": reason,
					"method": "shapely.make_valid (polygonale Bestandteile)"})
			if not isinstance(geometry, (Polygon, MultiPolygon)):
				raise ValueError(f"Feature {fid}: erwartet Polygon/MultiPolygon, erhalten {geometry.geom_type}")
			if geometry.is_empty or geometry.area <= 0:
				raise ValueError(f"Feature {fid}: leere oder flächenlose Geometrie")
			# Die Extraktion muss den Ausschnitt bereits exakt zugeschnitten haben.
			outside_area = geometry.difference(clip_area).area
			max_outside_area = max(max_outside_area, outside_area)
			if outside_area > 0.01:
				outside_tolerance_count += 1
			categories[int(code)].append(geometry)
			labels[int(code)][str(label).strip() if label is not None else ""] += 1

	if total != metadata.get("feature_count"):
		raise ValueError(f"GeoPackage hat {total} Features, Extraktionsbericht meldet {metadata.get('feature_count')}")
	if outside_tolerance_count:
		raise ValueError(f"{outside_tolerance_count} Features liegen außerhalb der Extraktions-BBOX "
			f"(maximal {max_outside_area:.3f} m²); bitte Extraktion prüfen")
	if not total:
		raise ValueError("Keine Features im extrahierten GeoPackage")

	merged_classes = []
	rows = []
	label_conflicts = []
	for code in sorted(categories):
		label_counts = labels[code]
		# Bezeichnungen exakt aus der FMZK; abweichende Varianten transparent protokollieren.
		label = label_counts.most_common(1)[0][0]
		if len(label_counts) > 1:
			label_conflicts.append({"f_klasse": code, "variants": dict(label_counts)})
		merged = union_all(categories[code])
		merged_classes.append(merged)
		rows.append({
			"f_klasse": code,
			"f_klasse_text": label,
			"objekte": len(categories[code]),
			"flaeche_m2": round(merged.area, 2),
			"anteil_bbox_prozent": round(100 * merged.area / clip_area.area, 3),
		})

	union_area = union_all(merged_classes).area
	class_sum = sum(geom.area for geom in merged_classes)
	report = {
		"warning": "Anteile beziehen sich nur auf die gesamte Test-BBOX. Noch keine Abgrenzung öffentlicher Straßenflächen und kein Gartenstraßen-Score.",
		"source": str(source),
		"layer": "fmzk",
		"crs": "EPSG:31256",
		"bbox_lon_lat": list(bbox),
		"bbox_area_m2": round(clip_area.area, 2),
		"feature_count": total,
		"geometry_types_original": dict(geometry_types),
		"geometry_repairs": repair_log,
		"label_conflicts": label_conflicts,
		"outside_bbox_max_m2": round(max_outside_area, 5),
		"union_area_m2": round(union_area, 2),
		"overlap_across_classes_m2": round(max(0.0, class_sum - union_area), 2),
		"categories": rows,
	}
	output_dir.mkdir(parents=True, exist_ok=True)
	csv_path = output_dir / "fmzk_klassen.csv"
	with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
		writer = csv.DictWriter(file, fieldnames=list(rows[0]))
		writer.writeheader()
		writer.writerows(rows)
	(output_dir / "fmzk_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	print(f"FMZK: {total} Features, {len(rows)} Klassen, EPSG:31256")
	print(f"Test-BBOX: {clip_area.area:.2f} m²; erfasste Fläche (Vereinigung): {union_area:.2f} m²")
	print(f"Überlagerung zwischen Klassen: {report['overlap_across_classes_m2']:.2f} m²")
	if repair_log:
		print(f"Warnung: {len(repair_log)} ungültige Geometrien repariert; Details in fmzk_report.json")
	if label_conflicts:
		print(f"Warnung: {len(label_conflicts)} Klassen mit unterschiedlichen offiziellen Bezeichnungstexten")
	for row in rows:
		print(f"{row['f_klasse']:3d} {row['objekte']:5d} {row['flaeche_m2']:12.2f} m²  {row['f_klasse_text']}")
	print(f"Ausgabe: {output_dir.resolve()}")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
	args = parser.parse_args()
	try:
		analyze(args.source, args.out_dir)
	except (ValueError, FileNotFoundError, OSError, sqlite3.Error, KeyError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
