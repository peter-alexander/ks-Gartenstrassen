"""Wienweiter BEV-Kataster-Reader direkt aus lokalem metrischem MVT-Cache.

Die Testgebiets-Pipeline kann weiterhin ihre WGS84-GeoJSONs nutzen.
Wienweit werden BEV-nfl-Polygone aber NICHT via WGS84
exportiert und erneut in EPSG:31256 transformiert. So bleiben
sehr schmale Fragmente bei der Straßenraum-Klassifikation erhalten.

Alle Kacheln müssen bereits lokal durch analyze_kataster geprüft
worden sein. Keine Netzwerkanfrage und kein stilles Weglassen von
Polygonen > 0,05 m². Klassen A–D sind hier NICHT die Grundlage:
genutzt werden ausschließlich die wirklichen nfl-Klassen 95/65.
"""
from collections import Counter
import math
from pathlib import Path

from shapely import make_valid, union_all
from shapely.geometry import Polygon, MultiPolygon
from shapely.errors import GEOSException
from shapely.strtree import STRtree
from shapely.validation import explain_validity

from scripts.analyze_gpkg import polygonal_part
from scripts.analyze_kataster import read_tiles
from scripts.export_fmzk_strassenraum import (
	CORE_CODES, STREET_USAGE_CODES, cadastral_key, read_json,
)
from scripts.wienwide_grid import checksum

ZOOM = 16
MIN_FRAGMENT_M2 = 0.05


def _polygonal(fragment, *, label):
	if fragment.is_empty or fragment.area <= MIN_FRAGMENT_M2:
		return None
	original_area = fragment.area
	if not fragment.is_valid:
		fragment = make_valid(fragment)
	fragment = polygonal_part(fragment)
	if fragment is None or fragment.is_empty or not fragment.is_valid:
		raise ValueError(f"{label}: metrisches Polygon nicht reparierbar "
			f"(vorher {original_area:.6f} m²)")
	if original_area - fragment.area > max(.01, original_area * 1e-6):
		raise ValueError(f"{label}: Flächenverlust bei Geometriereparatur "
			f"{original_area-fragment.area:.6f} m²")
	return fragment


def _validate_nfl_union(merged, fragments, *, group):
	"""Ungültige Vereinigung nur bei nachgewiesener Flächenerhaltung reparieren.

	Voraussetzung: Jedes nfl-Fragment wurde zuvor als gültiges
	Polygon geprüft. Auch ein vorübergehend ungültiges GEOS-Union-
	Ergebnis darf keinen dieser Flächenbeiträge verlieren.
	"""
	if merged.is_empty or not math.isfinite(merged.area) or merged.area <= 0:
		raise ValueError(f"BEV-nfl-Gruppe {group}: vereinigte Fläche "
			"leer, nicht endlich oder nicht positiv")
	if merged.is_valid:
		if merged.geom_type not in ("Polygon", "MultiPolygon"):
			raise ValueError(f"BEV-nfl-Gruppe {group}: "
				f"Nicht-Polygon nach Vereinigung ({merged.geom_type})")
		return merged, None
	reason = explain_validity(merged)
	original_area = merged.area
	try:
		repaired = polygonal_part(make_valid(merged))
	except GEOSException as exc:
		raise ValueError(f"BEV-nfl-Gruppe {group}: make_valid "
			f"auf ungültiger Vereinigung fehlgeschlagen ({reason}): "
			f"{exc}") from exc
	if (repaired is None or repaired.is_empty or not repaired.is_valid
		or not isinstance(repaired, (Polygon, MultiPolygon))
		or not math.isfinite(repaired.area) or repaired.area <= 0):
		raise ValueError(f"BEV-nfl-Gruppe {group}: ungültige Vereinigung "
			f"nicht polygonal reparierbar ({reason})")
	# Kleine unvermeidbare Floating-Point-Toleranz, nicht eine
	# großflächige Generalisierung oder Abrundung von Kleinstflächen.
	tolerance = max(.01, original_area * 1e-8)
	difference = repaired.area - original_area
	if abs(difference) > tolerance:
		raise ValueError(f"BEV-nfl-Gruppe {group}: Reparatur würde "
			f"vereinigte Fläche um {difference:+.6f} m² ändern "
			f"(zulässig {tolerance:.6f} m²; {reason})")
	# Flächengleichheit allein genügt nicht: prüfen, ob tatsächlich
	# ALLE ursprünglichen, einzeln gültigen BEV-Fragmente in der
	# reparierten Vereinigung enthalten bleiben.
	uncovered = 0.
	for index, part in enumerate(fragments):
		try:
			loss = part.difference(repaired).area
		except GEOSException as exc:
			raise ValueError(f"BEV-nfl-Gruppe {group}: "
				f"Quellfragment {index} nicht gegen Reparatur prüfbar: "
				f"{exc}") from exc
		if not math.isfinite(loss):
			raise ValueError(f"BEV-nfl-Gruppe {group}: nicht-endlicher "
				f"Flächenverlust an Fragment {index}")
		uncovered += loss
		if uncovered > tolerance:
			raise ValueError(f"BEV-nfl-Gruppe {group}: Reparatur verliert "
				f"{uncovered:.6f} m² der Quellfragmente "
				f"(zulässig {tolerance:.6f} m², Fragment {index}; {reason})")
	event = {
		"gruppe": group,
		"grund": reason,
		"fragmente": len(fragments),
		"union_vorher_m2": original_area,
		"union_nachher_m2": repaired.area,
		"flaechendifferenz_m2": difference,
		"nicht_abgedeckte_quellfragmente_m2": uncovered,
		"toleranz_m2": tolerance,
		"methode": "make_valid und vollstaendige Quellfragment-Kontrolle",
	}
	print(f"BEV-nfl-Hinweis: {group}: ungültige Union nach "
		f"make_valid flächentreu repariert; "
		f"Delta {difference:+.6f} m², "
		f"nicht abgedeckt {uncovered:.6f} m²; "
		f"GEOS: {reason}")
	return repaired, event


def read_native_kataster_masks(kataster_dir, clip, fmzk_features, manifest,
		cache_dir, *, max_tiles=120):
	"""Nfl-Masken aus den *ursprünglichen* EPSG:31256-Polygonen.

	Das zugehörige analyze_kataster-Ergebnis liefert den überprüften
	Ausschnitt und die erwarteten Kerngrundstücke. Rohkacheln werden
	ausschließlich offline aus dem gemeinsamen BEV-Cache geladen.
	"""
	kataster_dir = Path(kataster_dir)
	cache_dir = Path(cache_dir)
	report = read_json(kataster_dir/"kataster_bericht.json")
	if report.get("zoom") != ZOOM:
		raise ValueError("Katasterbericht benötigt Zoomstufe 16")
	if report.get("fmzk_kern_klassen") != sorted(CORE_CODES):
		raise ValueError("Katasterbericht mit veralteten FMZK-Kernklassen; "
			"Katasterstufe unter neuer Ausgabe neu berechnen")
	bbox = report.get("bbox_lon_lat")
	expected_bbox = manifest.get("bbox_lon_lat")
	if (not isinstance(bbox,list) or not isinstance(expected_bbox,list)
		or len(bbox)!=4 or len(expected_bbox)!=4 or
		any(abs(float(a)-float(b))>1e-8
			for a,b in zip(bbox,expected_bbox))):
		raise ValueError("FMZK und Kataster stammen aus verschiedenen Testausschnitten")
	original_tiles=report.get("tiles_abgerufen")
	if (not isinstance(original_tiles,list) or not original_tiles
		or any(not isinstance(row,list) or len(row)!=3
			or row[0]!=ZOOM or any(not isinstance(value,int)
				for value in row) for row in original_tiles)):
		raise ValueError("Katasterbericht enthält keine gültige z16-Kachelliste")
	tile_ids=[tuple(tile) for tile in original_tiles]
	if len(set(tile_ids))!=len(tile_ids):
		raise ValueError("Katasterbericht enthält doppelte BEV-Kacheln")
	if len(tile_ids)>max_tiles:
		raise ValueError(f"Mehr als {max_tiles} BEV-Kacheln im Katasterbericht")
	# Provenienz jeder Ursprungsdatei; explizit KEIN Cache-Nachladen.
	source_hashes={}
	for z,x,y in tile_ids:
		path=cache_dir/"tiles"/str(z)/str(x)/f"{y}.pbf"
		if not path.is_file():
			raise FileNotFoundError(f"BEV-Rohkachel fehlt: {path}")
		source_hashes[f"{z}/{x}/{y}"]=checksum(path)
	parcels,nfl,actual_tiles=read_tiles(
		bbox,cache_dir,offline=True,max_tiles=max_tiles)
	if list(actual_tiles)!=tile_ids:
		raise ValueError("BEV-Kachelliste weicht vom geprüften Katasterbericht ab")
	core_shapes=[geom for _,code,_,geom in fmzk_features if code in CORE_CODES]
	if not core_shapes:
		raise ValueError("Keine FMZK-Kernflächen für die Katasterprüfung")
	core=union_all(core_shapes).intersection(clip)
	if core.is_empty or not core.is_valid:
		raise ValueError("FMZK-Kerngeometrie ungültig")
	selected=[]
	for key,geom in sorted(parcels.items()):
		clipped=geom.intersection(clip)
		if clipped.is_empty or clipped.area<=0:
			continue
		if clipped.intersection(core).area>0:
			selected.append((key,clipped))
	if len(selected)!=report.get("grundstuecke"):
		raise ValueError("Katasterbericht und metrische BEV-Rohdaten "
			f"unterscheiden sich: {len(selected)} statt "
			f"{report.get('grundstuecke')} Kerngrundstücke")
	if not selected:
		raise ValueError("Keine betroffenen Katastergrundstücke")
	# Einmaliger räumlicher Index: vermeidet für 811 Grundstücke
	# jeweils sämtliche nfl-Fragmente linear zu durchsuchen.
	nfl_polys=[geom for _,geom in nfl]
	if not nfl_polys:
		raise ValueError("Keine BEV-nfl-Flächen in den Rohkacheln")
	tree=STRtree(nfl_polys)
	parts={"strasse":[],"sonstige":[]}
	observed=Counter()
	repaired=0
	excluded_tiny=Counter()
	excluded_tiny_area=Counter()
	for (kgez,gnr),parcel in selected:
		for ix in tree.query(parcel,predicate="intersects"):
			props,geom=nfl[int(ix)]
			code=props.get("ns")
			if not str(code).isdigit():
				raise ValueError(f"Unbekannter nfl-Code bei {kgez}/{gnr}: {code!r}")
			code=int(code)
			fragment=geom.intersection(parcel)
			if fragment.is_empty:
				continue
			if fragment.area <= MIN_FRAGMENT_M2:
				excluded_tiny[code]+=1
				excluded_tiny_area[code]+=fragment.area
				continue
			needs_repair=not fragment.is_valid or fragment.geom_type=="GeometryCollection"
			fragment=_polygonal(fragment,
				label=f"BEV-nfl {kgez}/{gnr}, Code {code}")
			if needs_repair:
				repaired+=1
			observed[code]+=1
			parts["strasse" if code in STREET_USAGE_CODES else "sonstige"].append(fragment)
	# Eine vollständig geprüfte Kachel kann ausschließlich nfl-95/65
	# oder ausschließlich andere nfl-Codes aufweisen. Nur BEIDE
	# fehlende Masken sind ein Daten-/Zuordnungsproblem.
	if not parts["strasse"] and not parts["sonstige"]:
		raise ValueError("Keine verwertbaren BEV-nfl-Flächen auf den "
		"ausgewählten Kerngrundstücken (Schwelle 0,05 m²); "
		f"Rohfragmente {len(nfl)}, Kerngrundstücke {len(selected)}")
	union_repairs=[]
	masks={}
	for group in ("strasse","sonstige"):
		fragments=parts[group]
		if not fragments:
			masks[group]=Polygon()
			continue
		merged=union_all(fragments)
		masks[group],event=_validate_nfl_union(
			merged,fragments,group=group)
		if event is not None:
			union_repairs.append(event)
	street,other=masks["strasse"],masks["sonstige"]
	groups=("beide" if parts["strasse"] and parts["sonstige"]
		else "nur_strasse" if parts["strasse"] else "nur_sonstige")
	return street,other,{
		"quelle":"BEV-nfl-z16-direkt-metrisch-aus-geprueftem-lokalem-Kachelcache",
		"strassen_codes":sorted(STREET_USAGE_CODES),
		"nfl_rohfragmente":len(nfl),
		"nfl_fragmente":sum(observed.values()),
		"nfl_nutzungen_fragmente":dict(sorted(observed.items())),
		"nfl_gruppenstatus":groups,
		"nfl_strassenfragmente":len(parts["strasse"]),
		"nfl_sonstige_fragmente":len(parts["sonstige"]),
		"nfl_reparaturen":repaired,
		"nfl_vereinigungsreparaturen":union_repairs,
		"nfl_fragmente_bis_0_05m2_nicht_uebernommen":sum(excluded_tiny.values()),
		"nfl_kleinfragmente_m2":sum(excluded_tiny_area.values()),
		"betroffene_grundstuecke":len(selected),
		"strassenmaske_m2":street.area,
		"sonstige_maske_m2":other.area,
		"nfl_gegenseitige_ueberlagerung_m2":street.intersection(other).area,
		"bev_cache_anzahl":len(source_hashes),
		"bev_cache_sha256":source_hashes,
	}
