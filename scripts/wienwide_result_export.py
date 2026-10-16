"""Publish Wien-wide GIP section results without changing measured source data.

The 100 m² threshold applies to each complete GIP ID, never to tiles.
Full CSV/GPKG and unresolved V0 surfaces remain untouched for QA.
The published GeoJSON dissolves tile fragments in metric EPSG:31256,
then transforms the complete geometry to WGS84 for the Kartensammlung.
"""
import argparse
from contextlib import closing
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import sqlite3
from urllib.parse import quote

from pyproj import Transformer
from shapely import make_valid, set_precision, union_all
from shapely.geometry import Polygon, MultiPolygon, mapping
from shapely.ops import transform
from shapely.validation import explain_validity

from scripts.analyze_gpkg import decode_gpkg_geometry, polygonal_part
from scripts.wienwide_grid import checksum
from scripts.wienwide_gip_greening import CSV_COLUMNS

WGS84 = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform
METRIC = Transformer.from_crs("EPSG:4326", "EPSG:31256", always_xy=True).transform


def _collapsed_wgs84_parts(metric,wgs84):
	"""Erkennt nur fast flächenlose metrische Ringe, die in WGS84 Linie werden.

	Kein flächenhafter Teil darf aufgrund geringer Größe verschwinden.
	Die einzig erlaubten Kandidaten sind METRISCH gültige Polygone
	mit höchstens 1e-9 m² und höchstens 1 m Umfang, deren eigene
	WGS84-Projektion ungültig ist und nach make_valid KEINE
	polygonalen Teile mehr besitzt.
	"""
	if not isinstance(metric,MultiPolygon) or not isinstance(wgs84,MultiPolygon):
		return None,[]
	if len(metric.geoms)!=len(wgs84.geoms):
		return None,[]
	kept=[]
	dropped=[]
	for index,(part,projected) in enumerate(zip(metric.geoms,wgs84.geoms)):
		is_micro=(0<part.area<=1e-9 and 0<part.length<=1.)
		if is_micro and not projected.is_valid and projected.area==0:
			converted=make_valid(projected)
			if converted.is_valid and polygonal_part(converted) is None:
				dropped.append({
					"teilpolygon_index":index,
					"flaeche_m2":part.area,
					"umfang_m":part.length,
					"bounds_epsg31256":list(part.bounds),
					"wgs84_fehler":explain_validity(projected),
					"wgs84_degenerierter_typ":converted.geom_type,
				})
				continue
		kept.append(part)
	if not dropped or not kept:
		return None,[]
	remaining=MultiPolygon(kept)
	# Nie eine Quelle mutieren oder durch den Filter eine
	# ungültige/sich überschneidende Fläche erzeugen.
	if not remaining.is_valid or remaining.is_empty:
		raise ValueError("Ausschluss numerischer WGS84-Artefakte "
			"erzeugt ungültige Polygonfläche")
	omitted=sum(x["flaeche_m2"] for x in dropped)
	if (not math.isfinite(omitted) or omitted>1e-9 or
		abs(metric.area-remaining.area)>1e-9):
		raise ValueError("Ausschluss numerischer WGS84-Artefakte "
			"würde zu viel Fläche verändern")
	return remaining,dropped

def _verified_wgs84_baseline(geom, wgs84, gid, repair_events):
	"""Nur projektionsbedingte Kleinstartefakte in der Ausgabe reparieren.

	EPSG:31256 und alle Messgeometrien bleiben unverändert. Nach
	make_valid wird die WGS84-Fläche wieder metrisch projiziert.
	Für eine Freigabe müssen die Grenzen auf Zentimeterniveau
	identisch und die Flächenabweichungen mit dem normalen
	(auch bei gültiger Geometrie auftretenden) Roundtrip vereinbar sein.
	"""
	if wgs84.is_empty:
		raise ValueError(f"{gid}: WGS84-Geometrie leer")
	if wgs84.is_valid:
		return wgs84
	reason=explain_validity(wgs84)
	comparison_metric=geom
	dropped=[]
	method="make_valid nur auf WGS84-Publikationsgeometrie"
	repaired=None
	# Der Wien-GIP 10023323 enthält ein Polygon mit 2.3e-13 m²,
	# dessen Punkte nach WGS84 zur Linie zusammenfallen. Bei der
	# allgemeinen make_valid-Reparatur würde dessen 30-cm-Linie
	# die Hausdorff-Prüfung scheitern lassen, obwohl die Fläche
	# praktisch Null ist. Nur diesen nachweisbaren Sonderfall
	# VOR make_valid und nur im Publikationsweg ausschließen.
	remaining,candidates=_collapsed_wgs84_parts(geom,wgs84)
	if candidates:
		try:
			reprojected=transform(WGS84,remaining)
			if not reprojected.is_empty and reprojected.is_valid:
				repaired=reprojected
				comparison_metric=remaining
				dropped=candidates
				method="Nur nach WGS84 zu Linie kollabierte numerische "
				method+="Teilpolygone im GeoJSON weggelassen"
		except Exception as exc:
			raise ValueError(f"{gid}: WGS84-Normalisierung "
				f"numerischer Teilpolygone fehlgeschlagen: {exc}") from exc
	if repaired is None:
		try:
			repaired=polygonal_part(make_valid(wgs84))
		except Exception as exc:
			raise ValueError(f"{gid}: WGS84-Geometrie ungültig "
				f"({reason}); make_valid gescheitert: {exc}") from exc
	if (repaired is None or repaired.is_empty
		or not isinstance(repaired,(Polygon,MultiPolygon))
		or not repaired.is_valid):
		raise ValueError(f"{gid}: WGS84-Geometrie ungültig "
			f"({reason}); keine gültige polygonale Reparatur")
	back_repair_reason=None
	back_repair_delta=None
	try:
		back=transform(METRIC,repaired)
		if back.is_empty or not all(math.isfinite(v) for v in back.bounds):
			raise ValueError("Rückprojektion leer oder nicht endlich")
		if not back.is_valid:
			# Nur der Kontrollgeometrie helfen: EPSG:4326 ist an
			# dieser Stelle bereits gültig und bleibt UNVERÄNDERT.
			# Winzige WGS84-Ringe können bei der Rückprojektion
			# wieder in eine ungültige metrische Ringtopologie
			# kollabieren. Nie direkt aus dieser ungültigen Fläche
			# die GIS-Differenzen bestimmen.
			back_repair_reason=explain_validity(back)
			raw_back_area=back.area
			back_verified=polygonal_part(make_valid(back))
			if (back_verified is None or back_verified.is_empty
				or not isinstance(back_verified,(Polygon,MultiPolygon))
				or not back_verified.is_valid):
				raise ValueError("Rückprojektion nicht polygonal reparierbar: "
					+ back_repair_reason)
			back_repair_delta=back_verified.area-raw_back_area
			if (not math.isfinite(back_repair_delta)
				or abs(back_repair_delta)>max(.01,geom.area*1e-6)):
				raise ValueError("Rückprojektion verändert bei "
					f"Kontrollreparatur Fläche um {back_repair_delta:+.9f} m² "
					f"({back_repair_reason})")
			back=back_verified
		area_delta=back.area-comparison_metric.area
		outside=back.difference(comparison_metric).area
		missing=comparison_metric.difference(back).area
		boundary_shift=comparison_metric.boundary.hausdorff_distance(back.boundary)
	except Exception as exc:
		raise ValueError(f"{gid}: WGS84-Geometrie ungültig "
			f"({reason}); metrische Reparaturprüfung fehlgeschlagen: "
			f"{exc}") from exc
	# Der Normal-Roundtrip EPSG:31256 -> WGS84 -> EPSG:31256
	# besitzt im Wienraum eine Projektionsabweichung bis ca. 1 mm.
	# Flächensymdiff wächst dadurch mit der Grenzlänge.
	# Die cm-Grenze verhindert räumliche Umdeutung; zusätzliche
	# Flächenobergrenze verbietet z.B. verschwundene Innenflächen.
	area_tolerance=max(.01,geom.area*1e-6)
	difference_tolerance=max(.01,geom.boundary.length*.003)
	shift_tolerance=.01
	if (not all(math.isfinite(v) for v in (
			area_delta,outside,missing,boundary_shift))
		or abs(area_delta)>area_tolerance
		or outside>difference_tolerance
		or missing>difference_tolerance
		or boundary_shift>shift_tolerance):
		raise ValueError(f"{gid}: WGS84-Geometrie ungültig "
			f"({reason}); Reparatur nicht metrisch flächentreu: "
			f"Flächenänderung {area_delta:+.9f} m² (max {area_tolerance:.6f}), "
			f"zusätzlich {outside:.9f} m², fehlend {missing:.9f} m² "
			f"(je max {difference_tolerance:.6f}), "
			f"Grenzverschiebung {boundary_shift:.6f} m "
			f"(max {shift_tolerance:.3f})")
	repair_events.append({
		"gip_id":gid,
		"geos_grund":reason,
		"methode":method,
		"im_geojson_ausgelassene_degenerierte_teilpolygone":dropped,
		"urspruengliche_grenzabweichung_m":(
			geom.boundary.hausdorff_distance(back.boundary)
			if dropped else boundary_shift),
		"rueckprojektion_pruefgeometrie_geos_grund":back_repair_reason,
		"rueckprojektion_pruefgeometrie_reparatur_delta_m2":back_repair_delta,
		"flaechenabweichung_nach_rueckprojektion_m2":area_delta,
		"zusaetzlich_m2":outside,
		"fehlend_m2":missing,
		"grenzverschiebung_m":boundary_shift,
		"flaechentoleranz_m2":area_tolerance,
		"differenztoleranz_m2":difference_tolerance,
		"grenzverschiebung_toleranz_m":shift_tolerance,
	})
	return repaired


# 10 nm: weit unter der Genauigkeit metrischer GIP-Koordinaten,
# aber oberhalb der Rundungsartefakte in extrem dünnen Polygonen.
EXPORT_PRECISION_M=1e-8


def _verified_wgs84_precision(geom,wgs84,gid,repair_events):
	"""Kontrollierte Präzisionsnormalisierung NUR in der Publikation.

	set_precision(..., valid_output) entfernt topologisch kollabierte
	Nullflächen, auch wenn ihre linienartige Ausdehnung mehrere Meter
	beträgt. Eine bloße Erhöhung der Hausdorff-Grenze wäre nicht sicher:
	hier müssen ALLE Flächenunterschiede zum ORIGINAL nachgewiesen klein
	sein; die 1-cm-Grenze gilt weiterhin für jede erhaltene Grenze.
	"""
	# Die Fallback-Methode darf nur eine echte Transformation des
	# unveränderten Quellpolygons korrigieren, keine beliebig übergebene,
	# reparierte/verschobene WGS84-Geometrie.
	if not wgs84.equals_exact(transform(WGS84,geom),0):
		raise ValueError(f"{gid}: WGS84-Normalisierung nur für "
			"unveränderte Originaltransformation zulässig")
	normalized=set_precision(geom,EXPORT_PRECISION_M,mode="valid_output")
	if (normalized.is_empty or not normalized.is_valid
		or not isinstance(normalized,(Polygon,MultiPolygon))):
		raise ValueError(f"{gid}: metrische Präzisionsnormalisierung ungültig")
	normal_limit=max(1e-6,geom.boundary.length*1e-7)
	original_gain=normalized.difference(geom).area
	original_loss=geom.difference(normalized).area
	original_delta=normalized.area-geom.area
	original_boundary_shift=geom.boundary.hausdorff_distance(
		normalized.boundary)
	if (not all(math.isfinite(v) for v in (
			original_gain,original_loss,original_delta,
			original_boundary_shift))
		or original_gain>normal_limit
		or original_loss>normal_limit
		or abs(original_delta)>normal_limit):
		raise ValueError(f"{gid}: metrische Präzisionsnormalisierung "
			"verändert Fläche zu stark: "
			f"zusätzlich {original_gain:.9f} m², "
			f"fehlend {original_loss:.9f} m², "
			f"Bilanz {original_delta:+.9f} m² "
			f"(je max {normal_limit:.9f})")
	projected=transform(WGS84,normalized)
	if projected.is_empty or not projected.is_valid:
		raise ValueError(f"{gid}: WGS84-Geometrie bleibt nach "
			"metrischer Präzisionsnormalisierung ungültig")
	back=transform(METRIC,projected)
	inverse_reason=None
	inverse_delta=None
	if back.is_empty or not all(math.isfinite(v) for v in back.bounds):
		raise ValueError(f"{gid}: normalisierte Rückprojektion leer")
	if not back.is_valid:
		inverse_reason=explain_validity(back)
		raw_area=back.area
		back=polygonal_part(make_valid(back))
		if (back is None or back.is_empty or not back.is_valid
			or not isinstance(back,(Polygon,MultiPolygon))):
			raise ValueError(f"{gid}: normalisierte Rückprojektion "
				"nicht polygonal reparierbar")
		inverse_delta=back.area-raw_area
		if not math.isfinite(inverse_delta) or abs(inverse_delta)>max(
				.01,normalized.area*1e-6):
			raise ValueError(f"{gid}: normalisierte Rückprojektion "
				"verändert bei Reparatur die Fläche zu stark")
	area_delta=back.area-normalized.area
	extra=back.difference(normalized).area
	missing=normalized.difference(back).area
	shift=normalized.boundary.hausdorff_distance(back.boundary)
	area_limit=max(.01,geom.area*1e-6)
	difference_limit=max(.01,normalized.boundary.length*.003)
	if (not all(math.isfinite(v) for v in
			(area_delta,extra,missing,shift))
		or abs(area_delta)>area_limit
		or extra>difference_limit
		or missing>difference_limit
		or shift>.01):
		raise ValueError(f"{gid}: normalisierte WGS84-Ausgabe "
			"nicht metrisch flächentreu: "
			f"Flächenänderung {area_delta:+.9f} m² "
			f"(max {area_limit:.6f}), zusätzlich {extra:.9f} m², "
			f"fehlend {missing:.9f} m² "
			f"(je max {difference_limit:.6f}), "
			f"Grenzverschiebung {shift:.6f} m (max 0.010)")
	repair_events.append({
		"gip_id":gid,
		"geos_grund":explain_validity(wgs84),
		"methode":"metrische 10-nm-Präzisionsnormalisierung ausschließlich "
			"für die WGS84-Publikationsgeometrie",
		"praezisionsraster_m":EXPORT_PRECISION_M,
		"urspruengliche_ausgangsflaeche_m2":geom.area,
		"normalisierte_ausgangsflaeche_m2":normalized.area,
		"normalisierung_flaechenbilanz_m2":original_delta,
		"normalisierung_zusaetzlich_m2":original_gain,
		"normalisierung_fehlend_m2":original_loss,
		"normalisierung_flaechengrenze_m2":normal_limit,
		"normalisierung_grenzverschiebung_original_m":
			original_boundary_shift,
		"rueckprojektion_pruefgeometrie_geos_grund":inverse_reason,
		"rueckprojektion_pruefgeometrie_reparatur_delta_m2":inverse_delta,
		"flaechenabweichung_nach_rueckprojektion_m2":area_delta,
		"zusaetzlich_m2":extra,
		"fehlend_m2":missing,
		"grenzverschiebung_m":shift,
		"flaechentoleranz_m2":area_limit,
		"differenztoleranz_m2":difference_limit,
		"grenzverschiebung_toleranz_m":.01,
	})
	return projected


def _verified_wgs84(geom,wgs84,gid,repair_events):
	"""Primär bisherigen Export beibehalten, nur bei Grenzfehlern normalisieren."""
	baseline_repairs=[]
	try:
		result=_verified_wgs84_baseline(geom,wgs84,gid,baseline_repairs)
	except ValueError as original_exc:
		if "Reparatur nicht metrisch flächentreu" not in str(original_exc):
			raise
		# Numerisch nahezu flächenlose Ausläufer dürfen nicht als
		# geometrisch echte Meter-Verschiebungen legitimiert werden.
		# Die zusätzliche Präzisionsmethode wird separat geprüft.
		try:
			result=_verified_wgs84_precision(geom,wgs84,gid,repair_events)
		except Exception as precision_exc:
			raise ValueError(
				f"{original_exc}; 10-nm-Normalisierung ebenfalls "
				f"abgelehnt: {precision_exc}") from precision_exc
		return result
	else:
		repair_events.extend(baseline_repairs)
		return result

def _rows(path):
	with Path(path).open(newline="", encoding="utf-8") as source:
		reader = csv.DictReader(source)
		if reader.fieldnames != list(CSV_COLUMNS):
			raise ValueError("Unbekanntes GIP-Begrünungs-CSV-Schema")
		items = {}
		for row in reader:
			gid = row["gip_id"]
			if not gid or gid in items or row["fow"] != "3":
				raise ValueError(f"GIP-ID fehlt/doppelt oder FOW != 3: {gid}")
			area = float(row["abschnitt_flaeche_m2"])
			if not math.isfinite(area) or area <= 0:
				raise ValueError(f"{gid}: ungültige Abschnittsfläche")
			for area_key, percentage_key in (("boden_m2", "boden_pct"),
					("grm_kronen_m2", "grm_kronen_pct")):
				part, pct = row[area_key], row[percentage_key]
				if not part and not pct:
					if area_key == "boden_m2":
						raise ValueError(f"{gid}: Bodenwert fehlt")
					continue
				if not part or not pct:
					raise ValueError(f"{gid}: unvollständiger Grün-/Kronenwert")
				value, share = float(part), float(pct)
				if (not math.isfinite(value) or not math.isfinite(share)
						or value < -1e-8 or value > area + .01
						or abs(share - 100 * value / area) > 1e-6):
					raise ValueError(f"{gid}: ungültige {area_key}-Bilanz")
			if int(row["kachelteile"]) < 1:
				raise ValueError(f"{gid}: keine Kachelteile")
			items[gid] = row
	if not items:
		raise ValueError("Leere GIP-Ergebnistabelle")
	return items


def _read_gp_meta(db):
	try:
		entries = dict(db.execute("SELECT key,value FROM qa_provenienz"))
		return json.loads(entries["gip_begruenung_v1"])
	except (KeyError, sqlite3.Error, json.JSONDecodeError) as exc:
		raise ValueError("GeoPackage ohne passende Begrünungs-Provenienz") from exc


def _check_totals(db, items, meta):
	if meta.get("gip_ids") != len(items):
		raise ValueError("GIP-Zahl aus GeoPackage-Bericht weicht von CSV ab")
	stats = {}
	for gid, n, total, minimum, maximum in db.execute("""
		SELECT gip_id, COUNT(*), SUM(flaeche_m2),
			MIN(gip_gesamt_m2), MAX(gip_gesamt_m2)
		FROM gip_abschnitte GROUP BY gip_id"""):
		stats[gid] = (n, total, minimum, maximum)
	if set(stats) != set(items):
		raise ValueError("GeoPackage- und CSV-GIP-IDs unterscheiden sich")
	for gid, row in items.items():
		n, total, minimum, maximum = stats[gid]
		area = float(row["abschnitt_flaeche_m2"])
		tol = max(.01, area * 1e-8)
		if (n != int(row["kachelteile"]) or
				any(x is None or abs(x - area) > tol
					for x in (total, minimum, maximum))):
			raise ValueError(f"{gid}: Flächen-/Fragmentbilanz abweichend")
	if abs(sum(float(r["abschnitt_flaeche_m2"]) for r in items.values()) -
			meta["ausgewertete_abschnittsflaeche_m2"]) > max(.05, meta["ausgewertete_abschnittsflaeche_m2"] * 1e-6):
		raise ValueError("Abschnittsgesamtfläche weicht vom QA-Bericht ab")
	return stats


def _properties(row):
	properties = dict(row)
	for name in ("fow", "kachelteile"):
		properties[name] = int(row[name])
	for name in ("abschnitt_flaeche_m2", "boden_m2", "boden_pct",
			"boden_58_m2", "boden_69_m2", "boden_klassen_ueberlagerung_m2",
			"grm_kronen_m2", "grm_kronen_pct"):
		properties[name] = float(row[name]) if row[name] else None
	return properties


def export(csv_path, gpkg_path, out_dir, *, min_area_m2=100):
	csv_path, gpkg_path, out_dir = map(Path, (csv_path, gpkg_path, out_dir))
	if not math.isfinite(min_area_m2) or min_area_m2 < 0:
		raise ValueError("Mindestfläche muss endlich und nichtnegativ sein")
	if out_dir.exists():
		raise FileExistsError(f"Ausgabe existiert bereits: {out_dir}")
	temp = out_dir.with_name(out_dir.name + ".tmp")
	if temp.exists():
		raise FileExistsError(f"Temporäre Ausgabe existiert bereits: {temp}")
	items = _rows(csv_path)
	selected = {gid: row for gid, row in items.items()
		if float(row["abschnitt_flaeche_m2"]) >= min_area_m2}
	if not selected:
		raise ValueError("Keine GIP-ID erfüllt die Mindestfläche")
	uri = "file:" + quote(str(gpkg_path.resolve()), safe="/") + "?mode=ro"
	temp.mkdir(parents=True)
	try:
		projection_repairs = []
		with closing(sqlite3.connect(uri, uri=True)) as db:
			meta = _read_gp_meta(db)
			_check_totals(db, items, meta)
			with (temp / "gip_abschnitte.csv").open("w", encoding="utf-8", newline="") as dst:
				writer = csv.DictWriter(dst, fieldnames=CSV_COLUMNS)
				writer.writeheader()
				writer.writerows(selected.values())
			with (temp / "gip_abschnitte.geojson").open("w", encoding="utf-8") as dst:
				dst.write('{"type":"FeatureCollection","features":[')
				count = 0
				def emit_group(gid, parts):
					nonlocal count
					if not parts:
						return
					row = selected[gid]
					geom = union_all(parts)
					area = float(row["abschnitt_flaeche_m2"])
					if (geom.is_empty or not geom.is_valid or
							abs(geom.area - area) > max(.05, area * 1e-6)):
						raise ValueError(f"{gid}: Vereinigung verändert die Abschnittsfläche")
					wgs84 = _verified_wgs84(geom,transform(WGS84,geom),
						gid,projection_repairs)
					feature = {"type": "Feature", "id": gid,
						"properties": _properties(row), "geometry": mapping(wgs84)}
					if count:
						dst.write(",")
					json.dump(feature, dst, ensure_ascii=False, allow_nan=False,
							separators=(",", ":"))
					count += 1
				last_gid = None
				parts = []
				for fid, gid, blob, part_area in db.execute("""
					SELECT fid,gip_id,geom,flaeche_m2 FROM gip_abschnitte
					ORDER BY gip_id,fid"""):
					if gid != last_gid:
						if parts:
							emit_group(last_gid, parts)
						parts = []
						last_gid = gid
					if gid not in selected:
						continue
					geom = decode_gpkg_geometry(blob, fid)
					if not geom.is_valid or geom.is_empty or geom.area <= 0:
						raise ValueError(f"{gid}/{fid}: ungültige Polygongeometrie")
					if abs(geom.area - part_area) > max(.01, part_area * 1e-8):
						raise ValueError(f"{gid}/{fid}: Geometrie/Fläche inkonsistent")
					parts.append(geom)
				if parts:
					emit_group(last_gid, parts)
				if count != len(selected):
					raise ValueError("Gefilterte GIP-Geometrien unvollständig")
				dst.write("]}\n")
		all_area = sum(float(r["abschnitt_flaeche_m2"]) for r in items.values())
		kept_area = sum(float(r["abschnitt_flaeche_m2"]) for r in selected.values())
		report = {
			"schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
			"min_area_m2": min_area_m2,
			"source_csv_sha256": checksum(csv_path),
			"source_gpkg_sha256": checksum(gpkg_path),
			"full_gip_ids": len(items), "output_gip_ids": len(selected),
			"omitted_gip_ids": len(items) - len(selected),
			"full_assigned_m2": all_area, "output_assigned_m2": kept_area,
			"omitted_assigned_m2": all_area - kept_area,
			"full_street_m2": meta.get("strassenraum_m2"),
			"full_unassigned_m2": meta.get("nicht_in_abschnittsquoten_m2"),
			"wgs84_projection_repairs": projection_repairs,
			"wgs84_projection_repair_count": len(projection_repairs),
			"note": "Nur Ausgabe gefiltert; vollständiges QA-GPKG bleibt erhalten. "
				"100 m² gelten pro globaler GIP-ID, nicht pro Kachelfragment."
		}
		(temp / "export_bericht.json").write_text(
			json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
		temp.replace(out_dir)
		return report
	except BaseException:
		shutil.rmtree(temp)
		raise


def main():
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("--csv", required=True, type=Path)
	p.add_argument("--gpkg", required=True, type=Path)
	p.add_argument("--out-dir", required=True, type=Path)
	p.add_argument("--min-area-m2", type=float, default=100)
	args = p.parse_args()
	try:
		report = export(args.csv, args.gpkg, args.out_dir,
			min_area_m2=args.min_area_m2)
		print(json.dumps(report, ensure_ascii=False, indent=2))
	except (ValueError, OSError, KeyError, TypeError, sqlite3.Error) as exc:
		p.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
