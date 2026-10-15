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
from pathlib import Path

from shapely import make_valid, union_all
from shapely.strtree import STRtree

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
	if not parts["strasse"] or not parts["sonstige"]:
		raise ValueError("BEV-nfl benötigt Straßen- und sonstige Nutzungsflächen")
	street=union_all(parts["strasse"])
	other=union_all(parts["sonstige"])
	if not street.is_valid or not other.is_valid:
		raise ValueError("Metrische BEV-nfl-Vereinigung ungültig")
	return street,other,{
		"quelle":"BEV-nfl-z16-direkt-metrisch-aus-geprueftem-lokalem-Kachelcache",
		"strassen_codes":sorted(STREET_USAGE_CODES),
		"nfl_rohfragmente":len(nfl),
		"nfl_fragmente":sum(observed.values()),
		"nfl_nutzungen_fragmente":dict(sorted(observed.items())),
		"nfl_reparaturen":repaired,
		"nfl_fragmente_bis_0_05m2_nicht_uebernommen":sum(excluded_tiny.values()),
		"nfl_kleinfragmente_m2":sum(excluded_tiny_area.values()),
		"betroffene_grundstuecke":len(selected),
		"strassenmaske_m2":street.area,
		"sonstige_maske_m2":other.area,
		"nfl_gegenseitige_ueberlagerung_m2":street.intersection(other).area,
		"bev_cache_anzahl":len(source_hashes),
		"bev_cache_sha256":source_hashes,
	}
