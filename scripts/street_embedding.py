"""Richtungsbasierte Randkontakte für FMZK-Prüfpolygone.

Die Richtungen beziehen sich auf die *äußere Normale der Polygonkante*,
nicht auf ihre Lage zum Schwerpunkt. Dadurch erzeugt eine lange einzelne
Gartengrenze keine scheinbar gegenüberliegenden Kontakte.

Das ist ein topologisches Suchsignal, kein Beleg für öffentlichen Straßenraum.
"""

from collections import defaultdict
import math

from shapely import union_all
from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point
from shapely.prepared import prep

CORE_CLASSES = (21, 23, 24, 33, 39)
DIRECTIONS = ("O", "NO", "N", "NW", "W", "SW", "S", "SO")


def make_contact_surfaces(features):
	by_class = defaultdict(list)
	for _, code, _, geometry in features:
		if code in CORE_CLASSES:
			by_class[code].append(geometry)
	surfaces = {code: union_all(geometries) for code, geometries in by_class.items()}
	if not surfaces:
		raise ValueError("Keine Straßenkernklassen gefunden")
	return surfaces


def line_parts(geometry):
	if geometry.is_empty:
		return
	if isinstance(geometry, LineString):
		if geometry.length > 0:
			yield geometry
	elif isinstance(geometry, (MultiLineString, GeometryCollection)):
		for part in geometry.geoms:
			yield from line_parts(part)


def normal_sector_lengths(contact_lines, polygon, *, probe_m=0.03):
	"""Verteile echte Randkontaktlängen auf 8 Außen-Normalrichtungen.

	Die Orientierung jeder Linie kann durch GEOS beliebig umgedreht werden.
	Daher wird durch kleine Testpunkte beiderseits der Kante ermittelt, wo
	die Fläche liegt. Nicht eindeutig orientierbare Teilstücke bleiben
	unbewertet und werden ausdrücklich separat protokolliert.
	"""
	inside = prep(polygon)
	sectors = [0.0] * 8
	unresolved_m = 0.0
	for line in line_parts(contact_lines):
		coordinates = list(line.coords)
		for (ax, ay), (bx, by) in zip(coordinates[:-1], coordinates[1:]):
			dx, dy = bx - ax, by - ay
			length = math.hypot(dx, dy)
			if length <= 1e-9:
				continue
			mx, my = (ax + bx) / 2, (ay + by) / 2
			nx, ny = -dy / length, dx / length
			left = inside.covers(Point(mx + nx * probe_m, my + ny * probe_m))
			right = inside.covers(Point(mx - nx * probe_m, my - ny * probe_m))
			if left == right:
				unresolved_m += length
				continue
			out_x, out_y = (-nx, -ny) if left else (nx, ny)
			theta = math.atan2(out_y, out_x)
			sector = int(((theta + math.pi / 8) % (2 * math.pi)) / (math.pi / 4))
			sectors[sector] += length
	return sectors, unresolved_m


def opposing_pairs(lengths_a, lengths_b, minimum):
	return [
		(i, j) for i, a in enumerate(lengths_a) if a >= minimum
		for j, b in enumerate(lengths_b) if b >= minimum
		if min((j - i) % 8, (i - j) % 8) >= 3
	]


def measure_embedding(
	geometry, class_surfaces, *,
	tolerance_m=0.25, minimum_sector_m=0.8,
	probe_m=0.03, has_core_overlap=False,
	prepared_class_buffers=None, prepared_core_buffer=None,
):
	"""Mehrseitige Kontaktlage; keine automatische Zurechnung zum Straßenraum."""
	if tolerance_m <= 0 or minimum_sector_m <= 0 or probe_m <= 0:
		raise ValueError("Kontakttoleranz, Mindestkontakt und Prüfpunktabstand müssen positiv sein")
	if geometry.is_empty or geometry.area <= 0:
		raise ValueError("Zu prüfende Geometrie muss eine Fläche enthalten")
	boundary = geometry.boundary
	by_class = {}
	for code in CORE_CLASSES:
		surface = class_surfaces.get(code)
		if surface is None or surface.is_empty or geometry.distance(surface) > tolerance_m:
			continue
		buffered = (prepared_class_buffers or {}).get(code)
		if buffered is None:
			buffered = surface.buffer(tolerance_m)
		lines = boundary.intersection(buffered)
		by_class[code], _ = normal_sector_lengths(lines, geometry, probe_m=probe_m)

	if prepared_core_buffer is None:
		prepared_core_buffer = union_all(list(class_surfaces.values())).buffer(tolerance_m)
	contact = boundary.intersection(prepared_core_buffer)
	sectors, unresolved_m = normal_sector_lengths(contact, geometry, probe_m=probe_m)
	opposing = bool(opposing_pairs(sectors, sectors, minimum_sector_m))
	different_classes_opposing = any(
		opposing_pairs(by_class[left], by_class[right], minimum_sector_m)
		for left in by_class for right in by_class if left < right
	)
	# Gleiche Klasse auf beiden Seiten wird ebenfalls erfasst, z.B. Baumscheibe
	# vollständig innerhalb eines Gehsteigs.
	contact_by_class = {code: round(sum(by_class.get(code, ())), 2) for code in CORE_CLASSES}
	active_codes = [code for code in CORE_CLASSES if contact_by_class[code] >= minimum_sector_m]
	if has_core_overlap:
		kind = "ueberlappung_pruefen"
	elif different_classes_opposing:
		kind = "mehrseitig_verschiedene_klassen"
	elif opposing:
		kind = "mehrseitig"
	elif any(value >= minimum_sector_m for value in sectors):
		kind = "einseitig"
	else:
		kind = "kein_deutlicher_randkontakt"

	return {
		"einbettung": kind,
		"mehrseitiger_kontakt": opposing,
		"gegenueber_verschiedene_klassen": different_classes_opposing,
		"kontaktklassen": ",".join(map(str, active_codes)),
		"kontakt_sektoren": ",".join(DIRECTIONS[i] for i, value in enumerate(sectors) if value >= minimum_sector_m),
		"kontakt_rand_pct": round(100 * sum(sectors) / boundary.length, 2) if boundary.length else 0,
		"richtung_ungeklaert_m": round(unresolved_m, 2),
		**{f"kontakt_{code}_m": contact_by_class[code] for code in CORE_CLASSES},
	}
