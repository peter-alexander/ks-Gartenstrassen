"""Topologische Indikatoren für FMZK-Prüfflächen, KEINE automatische Widmung.

Messung in EPSG:31256. Mehrseitiger Randkontakt kann Grüninseln/Baumscheiben
hervorheben, beweist aber weder Eigentum noch Zugänglichkeit.
"""

from collections import defaultdict
import math

from shapely import union_all
from shapely.geometry import GeometryCollection, LineString, MultiLineString

CORE_CLASSES = (21, 23, 24, 33, 39)
DIRECTIONS = ("O", "NO", "N", "NW", "W", "SW", "S", "SO")


def make_contact_surfaces(features):
	"""Einmal pro Kernklasse vereinigen; darauf beruhen alle Kandidatenmetriken."""
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


def sector_lengths(lines, center, *, sample_step_m=0.5):
	"""Kontaktlängen winkelweise auf 8 Richtungssektoren verteilen.

	Längere Linien werden abschnittweise abgetastet, damit nicht ihr einziger
	Mittelpunkt entscheidet. Der Schwerpunkt ist nur eine heuristische Referenz.
	"""
	result = [0.0] * 8
	for line in line_parts(lines):
		count = max(1, math.ceil(line.length / sample_step_m))
		length_piece = line.length / count
		for index in range(count):
			point = line.interpolate((index + 0.5) * length_piece)
			angle = math.atan2(point.y - center.y, point.x - center.x)
			sector = int((angle + math.pi / 8) % (2 * math.pi) / (math.pi / 4))
			result[sector] += length_piece
	return result


def opposing_pairs(lengths_a, lengths_b, minimum):
	return [
		(i, j) for i, amount_a in enumerate(lengths_a) if amount_a >= minimum
		for j, amount_b in enumerate(lengths_b) if amount_b >= minimum
		if min((j - i) % 8, (i - j) % 8) >= 3
	]


def measure_embedding(
	geometry, class_surfaces, *,
	tolerance_m=0.25, minimum_sector_m=0.8,
	sample_step_m=0.5, has_core_overlap=False,
):
	"""Merkmale für räumliche Einbettung von Grün-/unklaren Polygonen.

	Die Randkontaktlinien entstehen aus Schnitt der Polygonbegrenzung mit
	gepufferten Kernflächen. Ecken und sehr kurze Kontakte werden über die
	Mindestlänge je Richtungssektor abgeschwächt.
	"""
	if tolerance_m <= 0 or minimum_sector_m <= 0 or sample_step_m <= 0:
		raise ValueError("Kontakttoleranz, Mindestkontakt und Stichprobenabstand müssen positiv sein")
	center = geometry.centroid
	boundary = geometry.boundary
	by_class = {}
	for code in CORE_CLASSES:
		surface = class_surfaces.get(code)
		if surface is None or surface.is_empty:
			continue
		if geometry.distance(surface) > tolerance_m:
			continue
		lines = boundary.intersection(surface.buffer(tolerance_m))
		by_class[code] = sector_lengths(lines, center, sample_step_m=sample_step_m)

	all_class_geometries = list(class_surfaces.values())
	core = union_all(all_class_geometries)
	contact = boundary.intersection(core.buffer(tolerance_m))
	sectors = sector_lengths(contact, center, sample_step_m=sample_step_m)
	opposing = bool(opposing_pairs(sectors, sectors, minimum_sector_m))
	different_classes_opposing = any(
		opposing_pairs(by_class[left], by_class[right], minimum_sector_m)
		for left in by_class
		for right in by_class
		if left != right
	)
	contact_by_class = {code: round(sum(by_class.get(code, [])), 2) for code in CORE_CLASSES}
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
		**{f"kontakt_{code}_m": contact_by_class[code] for code in CORE_CLASSES},
	}
