#!/usr/bin/env python3
"""Modul 5 / V1-Diagnose: Straßenarm-Querprofile und Eck-Übergänge.

Nur ein explorativer Geometrietest. Aus der ORIGINALEN Straßenraummaske
und den geprüften GIP-Achsen/Knoten werden für ausgewählte Kreuzungen
Querschnittsprofile und – wenn nachweisbar – Übergangspunkte / Schnittlinien
abgeleitet. V0-Abschnitte und Straßenraum bleiben vollkommen unverändert.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import median

from shapely import union_all

from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon, MultiPolygon, mapping, shape
from shapely.ops import transform

DEFAULT_STREET = Path("data/processed/street_space/fmzk_strassenraum.geojson")
DEFAULT_FMZK = Path("data/processed/fmzk_test.gpkg")
DEFAULT_GIP = Path("data/processed/strassenabschnitte/gip")
DEFAULT_OUTPUT = Path("data/processed/strassenabschnitte/eckpunkte_diagnose_v1")
METRIC = Transformer.from_crs("EPSG:4326", "EPSG:31256", always_xy=True).transform
LONLAT = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform
STEP_M = 0.75
MAX_SEARCH_M = 28.0
CROSS_HALF_M = 45.0
MIN_BASELINE_M = 4.0
MAX_JUNCTIONS = 8
BOUNDARY_MODES = ("hauswand", "gehsteigkante")


def fahrbahn_mask(fmzk_features, street):
	"""Nur FMZK-Fahrbahn (21) als Fahrbahnrand-/Bordkanten-Näherung.

	Nicht als amtliche oder vollständig vermessene Gehsteigkante ausgeben:
	Parkbuchten, Zufahrten, Inseln und andere FMZK-Klassen fehlen.
	"""
	parts = [geometry.intersection(street)
		for _fid, code, _label, geometry in fmzk_features if code == 21
		and geometry.intersects(street)]
	parts = [part for part in parts if not part.is_empty and part.area > 0]
	if not parts:
		raise ValueError("Für Gehsteigkanten-Näherung keine FMZK-Fahrbahnklasse 21 im Straßenraum")
	mask = union_all(parts)
	if mask.is_empty or not mask.is_valid or mask.area <= 0:
		raise ValueError("FMZK-Fahrbahnmaske leer oder ungültig")
	return mask



def _required_id(value, label):
	if value is None or isinstance(value, bool) or not str(value).strip():
		raise ValueError(f"{label}: fehlende Kennung")
	return str(value).strip()


def _segments(geometry):
	if geometry.is_empty:
		return []
	if geometry.geom_type == "LineString":
		return [geometry] if geometry.length > 0 else []
	if hasattr(geometry, "geoms"):
		return [part for geom in geometry.geoms for part in _segments(geom)]
	return []


def _metric_street(street):
	if not isinstance(street, (Polygon, MultiPolygon)) or (
		street.is_empty or not street.is_valid or street.area <= 0
	):
		raise ValueError("Gültige metrische Straßenraum-Polygonmaske benötigt")
	return street


def _model(axes_features, node_features):
	nodes = {}
	for feature in node_features:
		props = feature.get("properties") or {}
		id_ = _required_id(props.get("gip_objectid"), "Knoten")
		if id_ in nodes:
			raise ValueError(f"Doppelte GIP-Knoten-ID: {id_}")
		p = transform(METRIC, shape(feature["geometry"]))
		if p.geom_type != "Point" or p.is_empty:
			raise ValueError(f"Knoten {id_}: ungültige Geometrie")
		nodes[id_] = {"id": id_, "name": props.get("name") or "",
			"point": p}
	axes = {}
	incident = defaultdict(list)
	for feature in axes_features:
		props = feature.get("properties") or {}
		id_ = _required_id(props.get("gip_objectid"), "Achse")
		if id_ in axes:
			raise ValueError(f"Doppelte GIP-Achsen-ID: {id_}")
		start = _required_id(props.get("node_from"), f"Achse {id_} Start")
		end = _required_id(props.get("node_to"), f"Achse {id_} Ende")
		geom = transform(METRIC, shape(feature["geometry"]))
		if geom.geom_type != "LineString" or geom.is_empty or geom.length <= 0:
			raise ValueError(f"Achse {id_}: LineString erwartet")
		fow = props.get("fow")
		axes[id_] = {"id": id_, "name": props.get("name") or "",
			"start": start, "end": end, "line": geom, "fow": fow}
		incident[start].append((id_, True))
		incident[end].append((id_, False))
	return nodes, axes, incident


def _oriented(line, from_start):
	if from_start:
		return line
	return LineString(list(line.coords)[::-1])


def _profile(street, oriented, distance, *, cross_half_m=CROSS_HALF_M):
	length = oriented.length
	h = min(1.0, length / 4, distance / 2, (length-distance)/2)
	if h <= 0:
		return None, "linienende"
	a = oriented.interpolate(distance-h)
	b = oriented.interpolate(distance+h)
	dx, dy = b.x-a.x, b.y-a.y
	norm = math.hypot(dx, dy)
	if norm <= 1e-9:
		return None, "richtung_undefiniert"
	nx, ny = -dy/norm, dx/norm
	p = oriented.interpolate(distance)
	left_bound = (p.x+cross_half_m*nx, p.y+cross_half_m*ny)
	right_bound = (p.x-cross_half_m*nx, p.y-cross_half_m*ny)
	cross = LineString([right_bound, left_bound])
	segments = _segments(cross.intersection(street))
	containing = [seg for seg in segments if seg.distance(p) <= 0.05]
	if len(containing) != 1:
		return None, "mehrdeutiger_oder_ausserhalb_liegender_querschnitt"
	chosen = containing[0]
	# Alle Teilstrecken der Schnittgeraden behalten ihre Orientierung
	# nicht zwingend bei; Endpunkte anhand der Projektion sortieren.
	ends = sorted([Point(chosen.coords[0]), Point(chosen.coords[-1])],
		key=cross.project)
	right, left = ends
	# An großen Kreuzungen kann die quer verlaufende Straße den
	# gesamten 90-m-Messstrahl füllen. Dieser *abgeschnittene* Wert
	# dient ausschließlich als Nachweis einer Aufweitung; er darf
	# niemals als echter Randpunkt / als stabile Normalbreite gelten.
	clipped_left = left.distance(Point(left_bound)) < 0.1
	clipped_right = right.distance(Point(right_bound)) < 0.1
	rr = right.distance(p)
	ll = left.distance(p)
	if ll < 0.05 or rr < 0.05:
		return None, "achse_am_rand"
	return {"s_m": distance, "axis": p, "left": left, "right": right,
		"left_m": ll, "right_m": rr, "width_m": ll+rr,
		"segment": chosen, "clipped_left": clipped_left,
		"clipped_right": clipped_right,
		"separate_intervals": len(segments)-1}, None


def _side_transition(profiles, side, *, step_m=STEP_M):
	"""Robuster, explizit konservativer Übergang: deutliche Aufweitung
	nahe dem Knoten, danach mindestens drei stabile Querprofile.
	Kein reiner Vertex- oder Maximalwinkel-Trick.
	"""
	valid = [p for p in profiles if p is not None]
	if len(valid) < 9:
		return None, "zu_wenige_profile"
	# Mindestens 4 m Messstrecke für stabile äußere Armzone.
	far_start = valid[-1]["s_m"]-max(MIN_BASELINE_M, .32*(
		valid[-1]["s_m"]-valid[0]["s_m"]))
	far = [p for p in valid
		if p["s_m"] >= far_start and not p[f"clipped_{side}"]]
	if len(far) < 5:
		return None, "basiszone_zu_kurz"
	base = median(p[f"{side}_m"] for p in far)
	mad = median(abs(p[f"{side}_m"]-base) for p in far)
	width_base = median(p["width_m"] for p in far)
	noise_limit = max(.55, .08*width_base)
	if mad > noise_limit:
		return None, "keine_stabile_normalbreite"
	deviation_limit = max(1.0, .12*width_base)
	# Nur echt verbreiterte Seiten, nicht bloße Verschmälerung zählen.
	widened = [i for i, p in enumerate(valid[:-4])
		if p[f"{side}_m"]-base > deviation_limit]
	if len(widened) < 2:
		return None, "keine_deutliche_aufweitung"
	# Mindestens zwei verbreiterte Profile müssen nahe des Knotens
	# auftreten. Breitenänderungen ganz am Datenrand ignorieren.
	if valid[widened[0]]["s_m"] >= far_start:
		return None, "aufweitung_ausserhalb_suchbereich"
	# Erste 3er-Folge unauffälliger Profile nach der letzten Aufweitung.
	last_widened = max(widened)
	tolerance = max(.65, .07*width_base)
	for i in range(last_widened+1, len(valid)-2):
		if all(not valid[j][f"clipped_{side}"]
			and abs(valid[j][f"{side}_m"]-base) <= tolerance
			for j in range(i, i+3)):
			return valid[i], None
	return None, "uebergang_ohne_stabile_folge"


def analyze(street, axis_features, node_features, *, node_ids=None,
	max_junctions=MAX_JUNCTIONS, step_m=STEP_M,
	max_search_m=MAX_SEARCH_M, cross_half_m=CROSS_HALF_M,
	boundary_mode="hauswand"):
	"""Datenunabhängig testbarer Diagnosekern; sämtliche Inputs EPSG:4326
	außer street, welches bereits metrisch EPSG:31256 vorliegt.
	"""
	_metric_street(street)
	if boundary_mode not in BOUNDARY_MODES:
		raise ValueError("Unbekannter Grenzmodus")
	if not (.25 <= step_m <= 2 and 8 <= max_search_m <= 45
		and 15 <= cross_half_m <= 100 and 1 <= max_junctions <= 38):
		raise ValueError("Parameter außerhalb der erlaubten Diagnosegrenzen")
	nodes, axes, incident = _model(axis_features, node_features)
	eligible = [nid for nid, n in nodes.items()
		if len(incident[nid]) >= 3]
	if node_ids:
		selected = [str(id_) for id_ in node_ids]
		if len(set(selected)) != len(selected):
			raise ValueError("Mehrfach angegebene Knoten-ID")
		if any(nid not in eligible for nid in selected):
			raise ValueError("Knoten fehlt oder hat weniger als 3 Arme")
		if len(selected) > max_junctions:
			raise ValueError("Mehr Knoten angegeben als --max-junctions")
	else:
		# Diversitätsprobe: reguläre 4- und 3-armige Knoten im Testgebiet.
		# Kurze Anbindungen werden zuerst berücksichtigt.
		def key(nid):
			items = incident[nid]
			nstandard = sum(axes[aid]["fow"] == 3 for aid, _ in items)
			minlength = min(axes[aid]["line"].length for aid, _ in items)
			return (nstandard != len(items), minlength, nid)
		groups = {4: sorted([nid for nid in eligible
			if len(incident[nid]) == 4], key=key),
			3: sorted([nid for nid in eligible
			if len(incident[nid]) == 3], key=key)}
		selected = []
		for degree in (4, 3):
			selected.extend(groups[degree][:max_junctions//2])
		if len(selected) < max_junctions:
			for nid in sorted(eligible, key=key):
				if nid not in selected:
					selected.append(nid)
					if len(selected) == max_junctions:
						break
		selected = selected[:max_junctions]
	geo = {"querprofile": [], "eckpunkte": [], "schnittlinien": []}
	records = []
	for node_id in selected:
		node = nodes[node_id]
		node_record = {"node_id": node_id, "name": node["name"],
			"degree": len(incident[node_id]), "arme": []}
		for axis_id, is_start in incident[node_id]:
			axis = axes[axis_id]
			line = _oriented(axis["line"], is_start)
			max_s = min(max_search_m, .5*line.length-1.0)
			arm = {"axis_id": axis_id, "name": axis["name"],
				"fow": axis["fow"], "length_m": round(line.length, 3),
				"max_search_distance_m": round(max_s, 3)}
			node_record["arme"].append(arm)
			if axis["fow"] != 3:
				arm["status"] = "sonderachse_fow"
				continue
			if max_s < max(8, 9*step_m):
				arm["status"] = "arm_zu_kurz"
				continue
			profiles = []
			errors = Counter()
			distance = max(1., step_m)
			while distance <= max_s+1e-7:
				p, err = _profile(street, line, distance,
					cross_half_m=cross_half_m)
				if err:
					errors[err] += 1
				if p:
					geo["querprofile"].append(_feature(p["segment"],
						{"node_id": node_id, "axis_id": axis_id,
							"name": axis["name"],
							"s_m": round(distance, 3),
							"width_m": round(p["width_m"], 3),
							"left_m": round(p["left_m"], 3),
							"right_m": round(p["right_m"], 3),
							"separate_intervals": p["separate_intervals"],
							"clipped_left": p["clipped_left"],
							"clipped_right": p["clipped_right"],
							"status": ("querschnitt_am_suchlimit"
								if p["clipped_left"] or p["clipped_right"]
								else "messung")}))
				profiles.append(p)
				distance += step_m
			arm["profile_count"] = len(profiles)
			arm["valid_profile_count"] = sum(p is not None for p in profiles)
			arm["profile_errors"] = dict(errors)
			left, left_error = _side_transition(profiles, "left",
				step_m=step_m)
			right, right_error = _side_transition(profiles, "right",
				step_m=step_m)
			arm["left_status"] = left_error or "kandidat"
			arm["right_status"] = right_error or "kandidat"
			# Bei dreiarmigen Kreuzungen liegt auf einer Seite oft eine
			# unveränderte Gerade ohne Aufweitung. Im Zweifelsfall:
			# Schnitt senkrecht zur lokalen GIP-Achse bei der gefundenen
			# Übergangsstation; zweiter Endpunkt = gegenüberliegender
			# Straßenrand derselben Querschnittsmessung. Auch wenn zwei
			# Übergänge erkannt wurden, die *äußere* Station wählen,
			# damit die Linie hinter beiden Eckrundungen liegt.
			orthogonal = len(incident[node_id]) == 3 and (
				left is not None or right is not None)
			selected_profile = None
			if orthogonal:
				selected_profile = max((p for p in (left, right)
					if p is not None), key=lambda p: p["s_m"])
				if selected_profile["clipped_left"] or selected_profile["clipped_right"]:
					arm["status"] = "querschnitt_am_suchlimit"
					continue
				cut = LineString([selected_profile["left"],
					selected_profile["right"]])
				cut_method = ("orthogonal_einseitig" if left is None
					or right is None else "orthogonal_beidseitig")
			else:
				if left is None or right is None:
					arm["status"] = "uebergang_unklar"
					continue
				cut = LineString([left["left"], right["right"]])
				cut_method = "eckpunkte_verbunden"
			# Neben Original-Eckpunkten bei T-Kreuzungen auch den
			# aus der Querschnittsmessung ergänzten Punkt exportieren.
			points = (("left", left), ("right", right))
			for side, p in points:
				if p is not None and (not orthogonal
					or p is selected_profile):
					pos = p[side]
					status = "kandidat_nicht_validiert"
				elif orthogonal:
					pos = selected_profile[side]
					status = "orthogonaler_gegenseitenpunkt_nicht_validiert"
				else:
					continue
				geo["eckpunkte"].append(_feature(pos,
					{"node_id": node_id, "axis_id": axis_id,
						"seite": side,
						"s_m": round(selected_profile["s_m"] if orthogonal
							else p["s_m"], 3),
						"methode": cut_method, "status": status}))
			intersection = cut.intersection(line)
			outside = cut.difference(street.buffer(.03)).length
			# Ein Punkt im Achskorridor und keine Durchdringung von
			# Straßenraum-Löchern / fremden Flächen.
			accepted = (cut.length >= 2 and cut.length <= 70
				and intersection.geom_type == "Point"
				and outside <= .03)
			arm["schnittlinie_m"] = round(cut.length, 3)
			arm["schnittmethode"] = cut_method
			arm["ausserhalb_strassenraum_m"] = round(outside, 3)
			arm["status"] = ("kandidat_pruefen" if accepted
				else "schnittlinie_geometrisch_abgelehnt")
			geo["schnittlinien"].append(_feature(cut,
				{"node_id": node_id, "axis_id": axis_id,
					"name": axis["name"],
					"status": arm["status"],
					"left_s_m": round(selected_profile["s_m"] if orthogonal
						else left["s_m"], 3),
					"right_s_m": round(selected_profile["s_m"] if orthogonal
						else right["s_m"], 3),
					"methode": cut_method,
					"grenzmodus": boundary_mode,
					"out_of_mask_m": round(outside, 3)}))
		records.append(node_record)
	armstatuses = Counter(a["status"] for n in records for a in n["arme"])
	return geo, {"schema_version": 1,
		"status": "DIAGNOSE – KEINE VALIDIERTE KREUZUNGSGRENZE",
		"parameter": {"step_m": step_m, "max_search_m": max_search_m,
			"cross_half_m": cross_half_m,
			"selected_junctions": len(selected),
			"boundary_mode": boundary_mode},
		"knoten": records, "arm_status_counts": dict(armstatuses),
		"geojson_feature_counts": {k: len(v) for k, v in geo.items()},
		"hinweis": "Punkte und Linien sind ungeprüfte Kandidaten. "
			"Keine Kreuzungspolygone, Abschnittsflächen oder "
			"Begrünungs-/Kronenwerte erzeugt."}


def _feature(geometry, properties):
	return {"type": "Feature", "properties": properties,
		"geometry": mapping(transform(LONLAT, geometry))}


def run(street_path=DEFAULT_STREET, fmzk=DEFAULT_FMZK,
	gip=DEFAULT_GIP, output=DEFAULT_OUTPUT, *, node_ids=None,
	max_junctions=MAX_JUNCTIONS, step_m=STEP_M,
	max_search_m=MAX_SEARCH_M, cross_half_m=CROSS_HALF_M,
	boundary_mode="hauswand"):
	"""Lädt ausschließlich vorhandene lokale Geodaten; kein WFS-Abruf."""
	from scripts.fmzk_source import load_polygons
	from scripts.measure_ground_greening import load_street_mask
	from scripts.analyze_gip_topology import audit, read_geojson

	output = Path(output)
	files = {"querprofile": output/"kreuzungen_querprofile.geojson",
		"eckpunkte": output/"kreuzungen_eckpunkte.geojson",
		"schnittlinien": output/"kreuzungen_schnittlinien.geojson",
		"bericht": output/"kreuzungen_diagnose_bericht.json"}
	if any(p.exists() for p in files.values()):
		raise FileExistsError(f"Diagnose existiert unter {output}; "
			"für weitere Varianten anderes --out-dir wählen")
	if boundary_mode not in BOUNDARY_MODES:
		raise ValueError("Unbekannter Grenzmodus")
	fmzk_features, manifest, clip, _ = load_polygons(fmzk)
	street, meta = load_street_mask(street_path, clip)
	profile_mask = (street if boundary_mode == "hauswand"
		else fahrbahn_mask(fmzk_features, street))
	gip = Path(gip)
	probe = json.loads((gip/"gip_probe_bericht.json").read_text(encoding="utf-8"))
	if probe.get("fmzk_bbox_lon_lat") != manifest.get("bbox_lon_lat"):
		raise ValueError("GIP- und FMZK-Test-BBOX passen nicht zusammen")
	axes_path = gip/"abschnitte_achsen.geojson"
	nodes_path = gip/"abschnitte_knoten.geojson"
	axes = read_geojson(axes_path, label="GIP-Achsen")
	nodes = read_geojson(nodes_path, label="GIP-Knoten")
	topology = audit(axes, nodes, probe)
	if topology["status"] != "topologie_konsistent":
		raise ValueError("GIP-Topologie inkonsistent; Diagnose abgebrochen")
	geo, report = analyze(profile_mask, axes, nodes, node_ids=node_ids,
		max_junctions=max_junctions, step_m=step_m,
		max_search_m=max_search_m, cross_half_m=cross_half_m,
		boundary_mode=boundary_mode)
	report["grenzreferenz"] = (
		"Modul-2-Straßenraumaußenrand (Gebäude-/Grundstücksgrenze)"
		if boundary_mode == "hauswand" else
		"FMZK F_KLASSE=21 Fahrbahnrand als Gehsteigkanten-Näherung; "
		"keine amtlich vermessene Bordsteinkante")
	report["profilmaske_m2"] = profile_mask.area
	report["created_utc"] = datetime.now(timezone.utc).isoformat()
	report["quellen"] = {
		"strassenraum": str(street_path),
		"strassenraum_sha256": meta["masken_sha256"],
		"gip_achsen": str(axes_path),
		"gip_achsen_sha256": hashlib.sha256(axes_path.read_bytes()).hexdigest(),
		"gip_knoten": str(nodes_path),
		"gip_knoten_sha256": hashlib.sha256(nodes_path.read_bytes()).hexdigest(),
		"fmzk_bbox_lon_lat": manifest["bbox_lon_lat"],
	}
	# Ausgabe erst nach vollständig beendeter Untersuchung.
	output.mkdir(parents=True, exist_ok=True)
	for kind, features in geo.items():
		(files[kind]).write_text(json.dumps(
			{"type": "FeatureCollection", "features": features},
			ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
	files["bericht"].write_text(json.dumps(report, ensure_ascii=False,
		indent=2)+"\n", encoding="utf-8")
	print(f"GIP-Kreuzungen geprüft: {len(report['knoten'])}")
	print(f"Arme: {report['arm_status_counts']}")
	print(f"Querprofile: {len(geo['querprofile'])}; "
		f"Eckpunkte: {len(geo['eckpunkte'])}; "
		f"Schnittlinien: {len(geo['schnittlinien'])}")
	print(f"Bericht: {files['bericht']}")
	return report


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--street-geojson", type=Path, default=DEFAULT_STREET)
	parser.add_argument("--fmzk", type=Path, default=DEFAULT_FMZK)
	parser.add_argument("--gip-dir", type=Path, default=DEFAULT_GIP)
	parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
	parser.add_argument("--node-id", action="append", default=[])
	parser.add_argument("--max-junctions", type=int, default=MAX_JUNCTIONS)
	parser.add_argument("--step-m", type=float, default=STEP_M)
	parser.add_argument("--max-search-m", type=float, default=MAX_SEARCH_M)
	parser.add_argument("--cross-half-m", type=float, default=CROSS_HALF_M)
	parser.add_argument("--boundary-mode", choices=BOUNDARY_MODES,
		default="hauswand", help="Außenrand oder FMZK-Fahrbahnrand als Gehsteigkanten-Näherung")
	args = parser.parse_args()
	try:
		run(street_path=args.street_geojson, fmzk=args.fmzk,
			gip=args.gip_dir, output=args.out_dir,
			node_ids=args.node_id or None,
			max_junctions=args.max_junctions, step_m=args.step_m,
			max_search_m=args.max_search_m, cross_half_m=args.cross_half_m,
			boundary_mode=args.boundary_mode)
	except (OSError, ValueError, TypeError, KeyError) as exc:
		parser.exit(1, f"Fehler: {exc}\n")


if __name__ == "__main__":
	main()
