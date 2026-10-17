"""SIS-Belagsflächen: reproduzierbarer GeoJSON-Pilot als V2-Straßenraumprovider.

Pilotquelle ist exakt SISBELAGOGD.json; keine Einschränkung auf Gehsteig-TYPEs.
Dieser Schritt berechnet noch keine GIP-Kanten und klassifiziert keine Entsiegelung.
Später kann ein gekachelter WFS-Adapter dieselbe Eingangsstruktur erzeugen.
"""
import argparse
import hashlib
import json
import lzma
from pathlib import Path
import shutil
import sqlite3
from urllib.request import urlopen

from pyproj import Transformer
from shapely import make_valid, union_all
from shapely.errors import GEOSException
from shapely.geometry import Polygon, MultiPolygon, shape
from shapely.ops import transform
from shapely.strtree import STRtree
from shapely.wkb import dumps
from shapely.validation import explain_validity

SOURCE_URL = "https://tiles.radlobby.at/Gehsteigbreiten/Testdaten/SISBELAGOGD.json"
SCHEMA = "sis-belagsflaechen-pilot-v1"
TO_METRIC = Transformer.from_crs("EPSG:4326", "EPSG:31256", always_xy=True).transform
MAX_SOURCE_BYTES = 150 * 1024 * 1024
VEGETATION_CODES = frozenset(("BL", "ST", "WI"))


def _polygonal_parts(geometry):
	"""Polygonale Bestandteile rekursiv erhalten; Linien/Punkte nie zu Fläche machen."""
	if isinstance(geometry, Polygon):
		return [geometry]
	if isinstance(geometry, MultiPolygon):
		return list(geometry.geoms)
	if hasattr(geometry, "geoms"):
		return [part for child in geometry.geoms for part in _polygonal_parts(child)]
	return []


def _repair_source_polygon(geom, *, index, identifier, sis_id, reason):
	"""Ungültige SIS-Fläche nur mit beidseitig belegter Flächentreue reparieren."""
	# Pilotentscheidung für den tatsächlich belegten Quellfehler: Ein
	# degenerierter Innenring trägt keine Fläche. Andere Topologiefehler
	# (z. B. Selbstüberschneidungen) bleiben fachlich mehrdeutig und brechen ab.
	if not reason.startswith("Too few points in geometry component"):
		raise ValueError(
			f"Feature {index} (ID {identifier!r}, SIS_ID {sis_id!r}): "
			f"ungültige Polygongeometrie: {reason}. "
			"Keine freigegebene konservative Reparatur für diesen Fehlertyp")
	try:
		candidate = make_valid(geom)
		parts = _polygonal_parts(candidate)
		repaired = union_all(parts) if parts else None
		original_metric = transform(TO_METRIC, geom)
		repaired_metric = transform(TO_METRIC, repaired) if repaired is not None else None
		if (repaired_metric is None or repaired_metric.is_empty
			or not repaired_metric.is_valid
			or not isinstance(repaired_metric, (Polygon, MultiPolygon))
			or repaired_metric.area <= 0):
			raise ValueError("make_valid lieferte keine gültige Polygonfläche")
		difference = repaired_metric.area - original_metric.area
		tolerance = max(.01, original_metric.area * 1e-8)
		symmetric_difference = original_metric.symmetric_difference(repaired_metric).area
		if abs(difference) > tolerance or symmetric_difference > tolerance:
			raise ValueError(
				f"Reparatur wäre nicht flächentreu: Delta {difference:+.6f} m², "
				f"symmetrische Differenz {symmetric_difference:.6f} m², "
				f"Toleranz {tolerance:.6f} m²")
	except (GEOSException, ValueError) as exc:
		raise ValueError(
			f"Feature {index} (ID {identifier!r}, SIS_ID {sis_id!r}): "
			f"ungültige Polygongeometrie: {reason}. "
			f"Streng geprüfte make_valid-Reparatur abgelehnt: {exc}") from exc
	event = {
		"feature_index": index,
		"feature_id": identifier,
		"sis_id": sis_id,
		"grund": reason,
		"methode": "shapely.make_valid; ausschließlich polygonale Bestandteile; metrische Flächentreue beidseitig geprüft",
		"make_valid_ergebnistyp": candidate.geom_type,
		"polygonale_bestandteile": len(parts),
		"verworfene_nichtpolygonale_bestandteile": [
			part.geom_type for part in getattr(candidate, "geoms", ())
			if not isinstance(part, (Polygon, MultiPolygon))],
		"flaeche_vorher_m2": original_metric.area,
		"flaeche_nachher_m2": repaired_metric.area,
		"flaechendifferenz_m2": difference,
		"symmetrische_differenz_m2": symmetric_difference,
		"toleranz_m2": tolerance,
	}
	return repaired, event


def download_source(url, destination):
	"""Nur die vorgegebene Testquelle, begrenzter Download, niemals überschreiben."""
	if url != SOURCE_URL:
		raise ValueError("Pilot erlaubt ausschließlich die vereinbarte SIS-Testquelle")
	if destination.exists():
		raise FileExistsError(destination)
	temporary = destination.with_suffix(".download")
	if temporary.exists():
		raise FileExistsError(temporary)
	try:
		with urlopen(url, timeout=90) as source, temporary.open("xb") as target:
			amount = 0
			while chunk := source.read(1024 * 1024):
				amount += len(chunk)
				if amount > MAX_SOURCE_BYTES:
					raise ValueError("SIS-Testquelle übersteigt 150 MiB")
				target.write(chunk)
		temporary.replace(destination)
	except BaseException:
		temporary.unlink(missing_ok=True)
		raise


def read_surfaces(path, *, repair_log=None, source_log=None):
	"""Alle Polygonfeatures mit sämtlichen TYPE-Werten, metrisch transformiert."""
	source = Path(path)
	if source.name.endswith(".geojson.xz"):
		with lzma.open(source,"rt",encoding="utf-8") as stream:
			doc = json.load(stream)
	else:
		doc = json.loads(source.read_text(encoding="utf-8"))
	if doc.get("type") != "FeatureCollection" or not isinstance(doc.get("features"), list):
		raise ValueError("SIS-Eingabe muss eine GeoJSON-FeatureCollection sein")
	if "crs" in doc:
		crs = doc["crs"]
		name = (crs.get("properties", {}).get("name")
			if isinstance(crs, dict) and crs.get("type") == "name"
			and isinstance(crs.get("properties"), dict) else None)
		if not isinstance(name, str) or name.strip().upper() not in (
			"EPSG:4326", "URN:OGC:DEF:CRS:EPSG::4326",
			"URN:OGC:DEF:CRS:EPSG:6.6:4326",
			"OGC:CRS84", "URN:OGC:DEF:CRS:OGC:1.3:CRS84"):
			raise ValueError(f"Nicht unterstütztes GeoJSON-CRS: {name!r}; WGS84 erwartet")
	if not doc["features"]:
		raise ValueError("SIS-FeatureCollection ist leer")
	rows = []
	for index, feature in enumerate(doc["features"]):
		if not isinstance(feature, dict) or feature.get("type") != "Feature":
			raise ValueError(f"Feature {index}: ungültige Struktur")
		props = feature.get("properties")
		if (not isinstance(props, dict) or not isinstance(props.get("TYPE"), str)
			or not isinstance(props.get("BELAG"), str)
			or not isinstance(props.get("BELAG_TXT"), str)):
			raise ValueError(f"Feature {index}: SIS TYPE/BELAG/BELAG_TXT fehlen")
		geom = shape(feature.get("geometry"))
		identifier = feature.get("id", f"Index {index}")
		sis_id = props.get("SIS_ID")
		if not isinstance(geom, (Polygon, MultiPolygon)) or geom.is_empty:
			raise ValueError(
				f"Feature {index} (ID {identifier!r}, SIS_ID {sis_id!r}): "
				"keine nichtleere Polygongeometrie")
		if not geom.is_valid:
			reason = explain_validity(geom)
			geom, event = _repair_source_polygon(geom, index=index,
				identifier=identifier, sis_id=sis_id, reason=reason)
			if repair_log is not None:
				repair_log.append(event)
		west, south, east, north = geom.bounds
		if not (15.5 < west <= east < 17.5 and 47.5 < south <= north < 49):
			raise ValueError(f"Feature {index}: Koordinaten außerhalb Wiens / Achsen vertauscht")
		metric = transform(TO_METRIC, geom)
		if not metric.is_valid or metric.is_empty or metric.area <= 0:
			raise ValueError(f"Feature {index}: ungültige metrische Fläche")
		rows.append((index, props["TYPE"], props["BELAG"], props["BELAG_TXT"], metric))
		if source_log is not None:
			source_log.append({"feature_index": index, "feature_id": identifier,
				"sis_id": sis_id, "type": props["TYPE"], "belag": props["BELAG"]})
	return rows


def _overlap_audit(rows, sources):
	"""Alle flächigen Quellüberlagerungen mit IDs und Klassifikation erfassen."""
	geometries = [row[4] for row in rows]
	tree = STRtree(geometries)
	events = []
	for index, geom in enumerate(geometries):
		for other in tree.query(geom, predicate="intersects"):
			other = int(other)
			if other <= index:
				continue
			area = geom.intersection(geometries[other]).area
			if area <= 1e-7:
				continue
			left, right = sources[index], sources[other]
			events.append({
				"feature_index_a": left["feature_index"],
				"feature_id_a": left["feature_id"], "sis_id_a": left["sis_id"],
				"type_a": left["type"], "belag_a": left["belag"],
				"feature_index_b": right["feature_index"],
				"feature_id_b": right["feature_id"], "sis_id_b": right["sis_id"],
				"type_b": right["type"], "belag_b": right["belag"],
				"ueberlagerung_m2": area,
				"gleiche_bodenklasse": ((left["belag"] in VEGETATION_CODES)
					== (right["belag"] in VEGETATION_CODES)),
			})
	return sorted(events, key=lambda event: -event["ueberlagerung_m2"])


def build(source, output):
	"""Original unverändert übernehmen, alle Einzelbeläge und Union indizieren."""
	source, output = Path(source), Path(output)
	if output.exists():
		raise FileExistsError(f"Vorhandener Pilotordner wird nicht überschrieben: {output}")
	if not source.is_file():
		raise FileNotFoundError(source)
	repairs, sources = [], []
	rows = read_surfaces(source, repair_log=repairs, source_log=sources)
	street = union_all([geom for _, _, _, _, geom in rows])
	if not street.is_valid or street.is_empty or street.area <= 0:
		raise ValueError("SIS-Gesamtfläche ungültig")
	gross = sum(g.area for _, _, _, _, g in rows)
	overlap = max(0., gross-street.area)
	tolerance = max(.01, gross*1e-8)
	overlap_events = _overlap_audit(rows, sources) if overlap > tolerance else []
	green = union_all([geom for _, _, belag, _, geom in rows
		if belag in VEGETATION_CODES])
	non_green = union_all([geom for _, _, belag, _, geom in rows
		if belag not in VEGETATION_CODES])
	class_conflict = green.intersection(non_green).area
	# Überlagerungen derselben binären Bodenklasse ändern die Klassifikation
	# nicht und werden durch Union nie doppelt gezählt. Widersprüchliche
	# Quellklassen dürfen nur numerische Randsplitter sein; dort gilt
	# konservativ „nicht begrünt“.
	conflict_tolerance = .01
	if class_conflict > conflict_tolerance:
		raise ValueError(
			f"SIS-Bodenklassen überlagern sich widersprüchlich um "
			f"{class_conflict:.6f} m² (Toleranz {conflict_tolerance:.6f} m²)")
	sha = hashlib.sha256(source.read_bytes()).hexdigest()
	output.mkdir(parents=True)
	try:
		if source.name.endswith(".geojson.xz"):
			# WFS-Kacheln bleiben einmalig im dauerhaften XZ-Cache.
			# Keine zweite Kopie und kein unkomprimiertes GeoJSON auf der SSD.
			archived_source = str(source.resolve())
		else:
			shutil.copyfile(source, output/"SISBELAGOGD.json")
			archived_source = str((output/"SISBELAGOGD.json").resolve())
		with sqlite3.connect(output/"sis.sqlite") as db:
			db.executescript("""
				CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
				CREATE TABLE surfaces (
					id INTEGER PRIMARY KEY, type TEXT NOT NULL,
					belag TEXT NOT NULL, belag_txt TEXT NOT NULL,
					area_m2 REAL NOT NULL, geom BLOB NOT NULL
				);
				CREATE VIRTUAL TABLE surface_index USING rtree(
					id,minx,maxx,miny,maxy
				);
				CREATE TABLE street (geom BLOB NOT NULL);
			""")
			for index, kind, belag, belag_txt, geom in rows:
				db.execute("INSERT INTO surfaces VALUES (?,?,?,?,?,?)",
					(index, kind, belag, belag_txt, geom.area, dumps(geom)))
				db.execute("INSERT INTO surface_index VALUES (?,?,?,?,?)",
					(index, geom.bounds[0], geom.bounds[2], geom.bounds[1], geom.bounds[3]))
			db.execute("INSERT INTO street VALUES (?)", (dumps(street),))
			for key, value in {"schema": SCHEMA, "crs": "EPSG:31256",
				"sha256": sha, "provider": "SISBELAGOGD",
				"source_path": archived_source,
				"source_url": SOURCE_URL,
				"geometry_repairs": json.dumps(repairs, ensure_ascii=False)}.items():
				db.execute("INSERT INTO metadata VALUES (?,?)", (key, value))
		counts = {}
		belags = {}
		for _, kind, belag, belag_txt, geom in rows:
			entry = counts.setdefault(kind, {"features": 0, "summierte_flaeche_m2": 0})
			entry["features"] += 1
			entry["summierte_flaeche_m2"] += geom.area
			b = belags.setdefault(belag, {"bezeichnung": belag_txt, "features": 0,
				"summierte_flaeche_m2": 0})
			if b["bezeichnung"] != belag_txt:
				raise ValueError(f"BELAG {belag}: widersprüchliche Bezeichnungen")
			b["features"] += 1
			b["summierte_flaeche_m2"] += geom.area
		report = {
			"schema": SCHEMA, "quelle": SOURCE_URL, "sha256": sha,
			"crs": "EPSG:31256", "features": len(rows),
			"brutto_summe_m2": gross,
			"vereinigte_strassenbelagsflaeche_m2": street.area,
			"ueberlagerungsflaeche_m2": overlap, "ueberlagerungstoleranz_m2": tolerance,
			"ueberlagerungspaare": overlap_events,
			"widerspruechliche_bodenklassen_m2": class_conflict,
			"widerspruechliche_bodenklassen_toleranz_m2": conflict_tolerance,
			"boden_ueberlagerungsregel": "BL/ST/WI nur außerhalb aller übrigen BELAG-Flächen begrünt; Konfliktflächen konservativ nicht begrünt",
			"geometriekorrekturen": repairs,
			"type_klassen": counts, "belag_klassen": belags,
			"status": "V2-Quellpilot; keine Entsiegelungsklassifikation und keine GIP-Abschnitte",
		}
		(output/"bericht.json").write_text(
			json.dumps(report, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
		return report
	except BaseException:
		shutil.rmtree(output)
		raise


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--source-file", type=Path, help="Bereits lokal vorhandene exakt gleiche Testdatei")
	parser.add_argument("--out-dir", type=Path,
		default=Path("data/processed/sis-pilot-v2"))
	args = parser.parse_args()
	if args.source_file is None:
		cache = Path("data/raw/sis/SISBELAGOGD.json")
		cache.parent.mkdir(parents=True, exist_ok=True)
		if not cache.exists():
			download_source(SOURCE_URL, cache)
		source = cache
	else:
		source = args.source_file
	print(json.dumps(build(source, args.out_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
	main()
