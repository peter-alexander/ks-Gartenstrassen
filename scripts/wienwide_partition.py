"""Wienweite GIP-V0-Partition kachelweise, aber mit GIP-GLOBALEN Sites.

Analyse je METERKACHEL, Halo dient nur für die Voronoi-Nachbarschaft.
Knotenradius 7, Stützpunktabstand 5, Achsbuffer 25 und FOW=3 wie V0.
Eingabe: metrisches street-WKB-SQLite je Kachel (siehe wienwide_street).
Ergebnis: SQLite-WKB je (Kachel, GIP-ID), alle ungeklärten Teile
und strenge Flächenbilanz. Kein GeoJSON-Rundweg in Berechnung.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
from time import perf_counter

from shapely import intersection, make_valid, union_all, voronoi_polygons
from shapely.errors import GEOSException
from shapely.geometry import MultiPoint, Polygon, MultiPolygon, box
from shapely.validation import explain_validity
from shapely.wkb import dumps, loads

from scripts.analyze_gpkg import polygonal_part
from scripts.assign_gip_section_areas import MAX_SITES
from scripts.wienwide_grid import read_manifest, checksum
from scripts.wienwide_gip import connect as connect_gip

SCHEMA = 1
GROUPS = ("knotenbereich","sonderachse","nicht_zugeordnet")
GIP2_INDEX_METHOD = "gip2-local-edge-turn-use-v1"


def _validate_index_metadata(metadata, manifest_sha256, *, gip2_hulls=False):
	common=(metadata.get("manifest_sha256")==manifest_sha256
		and metadata.get("sampling_m")==5
		and metadata.get("max_axis_distance_m")==25)
	method=(metadata.get("index_method")==GIP2_INDEX_METHOD
		if gip2_hulls else metadata.get("knotenradius_m")==7)
	if not common or not method:
		raise ValueError("GIP-Katalog gehört zu anderem AOI/anderer Methode")


def _describe_method(report, *, gip2_hulls=False):
	if gip2_hulls:
		report["status"]=("vorläufige GIP2-Aufteilung mit "
			"TURN_USE-Kreuzungshüllen; keine fachlich geprüfte Straßenabgrenzung")
		report["kreuzungen"]="gip2-turn-use-convex-hull"
	return report


def _polygon(g, label, *, witnesses=(), repair_events=None):
	"""Topologische Overlay-Artefakte streng flächentreu polygonalisieren.

	Nur eine tatsächlich ungültige Geometrie wird repariert. Gerade
	Voronoi-Zellen müssen nach der Reparatur innerhalb BEIDER
	ursprünglichen Schnittpartner liegen (Zelle und Restmaske).
	"""
	if g is None or g.is_empty:
		return None
	if not math.isfinite(g.area):
		raise ValueError(f"{label}: nicht-endliche Geometriefläche")
	if g.area <= 0:
		if not g.is_valid:
			raise ValueError(f"{label}: ungültige Geometrie mit "
				f"Nullfläche ({explain_validity(g)}); nicht still übergehen")
		return None
	poly=polygonal_part(g)
	if poly is None or poly.is_empty or poly.area <= 0:
		raise ValueError(f"{label}: keine positive Polygonfläche")
	if poly.is_valid:
		return poly
	reason=explain_validity(poly)
	area_before=poly.area
	try:
		repaired=polygonal_part(make_valid(poly))
	except GEOSException as exc:
		raise ValueError(f"{label}: ungültige polygonale Fläche "
			f"({reason}); make_valid fehlgeschlagen: {exc}") from exc
	if (repaired is None or repaired.is_empty
		or not isinstance(repaired,(Polygon,MultiPolygon))
		or not repaired.is_valid or not math.isfinite(repaired.area)
		or repaired.area <= 0):
		raise ValueError(f"{label}: ungültige polygonale Fläche "
			f"nicht reparierbar ({reason})")
	tolerance=max(.01,area_before*1e-8)
	delta=repaired.area-area_before
	if abs(delta)>tolerance:
		raise ValueError(f"{label}: ungültige polygonale Fläche "
			f"({reason}); Reparatur verändert Fläche um {delta:+.6f} m² "
			f"(zulässig {tolerance:.6f} m²)")
	provenance={}
	for name,original in witnesses:
		if original is None or not original.is_valid:
			raise ValueError(f"{label}: Prüfgeometrie {name} ungültig; "
				"Reparatur nicht verifizierbar")
		try:
			outside=repaired.difference(original).area
		except GEOSException as exc:
			raise ValueError(f"{label}: Prüfgeometrie {name} "
				f"nicht überlagerbar: {exc}") from exc
		if not math.isfinite(outside) or outside>tolerance:
			raise ValueError(f"{label}: Reparatur liegt um "
				f"{outside:.6f} m² außerhalb {name} "
				f"(zulässig {tolerance:.6f} m²; {reason})")
		provenance[name]=outside
	event={
		"kontext":label,"geos_grund":reason,
		"geometrie_typ":g.geom_type,
		"flaeche_vorher_m2":area_before,
		"flaeche_nachher_m2":repaired.area,
		"differenz_m2":delta,"toleranz_m2":tolerance,
		"ausserhalb_pruefgeometrien_m2":provenance,
		"methode":"make_valid, Flaechenbilanz und Schnittraumpruefung",
	}
	if repair_events is not None:
		repair_events.append(event)
	print(f"Partition-Hinweis: {label}: ungültige Polygonfläche "
		f"flächentreu repariert; Delta {delta:+.6f} m², "
		f"GEOS: {reason}")
	return repaired


def _check_overlay_intersection(candidate, left, right, label):
	"""Alternative Schnittfläche unabhängig und beidseitig prüfen.

	GEOS kann bei gültigen Quellpolygonen ein falsches Ergebnis
	für (left - candidate) ∩ right liefern (Wien: +1200,88 m²).
	Deshalb werden zwei unabhängig aufgerasterte Kontrollschnitte
	samt der Flächenaufteilung A = (A minus B) + (A Schnitt B) geprüft.
	Die Zellenrekonstruktion bleibt ungerundet.
	"""
	if not left.is_valid or not right.is_valid:
		raise ValueError(f"{label}: Ausgangsgeometrien für "
			"Voronoi-Overlayprüfung ungültig")
	if candidate is None:
		candidate=Polygon()
	if not candidate.is_valid or not math.isfinite(candidate.area):
		raise ValueError(f"{label}: ungültiges Ergebnis "
			"der alternativen Schnittberechnung")
	checks=[]
	failures=[]
	for grid in (1e-9,1e-8):
		try:
			reference_raw=intersection(left,right,grid_size=grid)
			reference=polygonal_part(reference_raw)
			if reference is None:
				reference=Polygon()
			if not reference.is_valid or not math.isfinite(reference.area):
				raise ValueError("Kontrollschnitt nicht polygonal gültig")
			left_only=left.difference(right,grid_size=grid)
			right_only=right.difference(left,grid_size=grid)
			# Diese unabhängigen Flächenidentitäten erkennen
			# eine falsch berechnete Schnittreferenz.
			balance_left=left.area-(left_only.area+reference.area)
			balance_right=right.area-(right_only.area+reference.area)
			balance_tol=max(.01,max(left.area,right.area)*1e-8)
			if (not math.isfinite(balance_left)
				or not math.isfinite(balance_right)
				or abs(balance_left)>balance_tol
				or abs(balance_right)>balance_tol):
				raise ValueError(f"Kontrollschnitt verletzt "
					f"Quellflächenbilanzen: A {balance_left:+.9f}, "
					f"B {balance_right:+.9f} m²; "
					f"Toleranz {balance_tol:.9f} m²")
			# Kleinstflächen nicht unter der bisherigen allgemeinen
			# 0,01-m²-Toleranz verschwinden lassen.
			tolerance=max(1e-8,
				min(.01,max(candidate.area,reference.area)*1e-6))
			missing=reference.difference(candidate,grid_size=grid).area
			measures={
				"ausserhalb_voronoi_zellen_m2":
					candidate.difference(left,grid_size=grid).area,
				"ausserhalb_uebrigem_strassenraum_m2":
					candidate.difference(right,grid_size=grid).area,
				"fehlend_von_voronoi_zellen_m2":missing,
				"fehlend_vom_uebrigen_strassenraum_m2":missing,
				"zusaetzlich_gegen_kontrollschnitt_m2":
					candidate.difference(reference,grid_size=grid).area,
			}
			if any(not math.isfinite(value) or value>tolerance
				for value in measures.values()):
				raise ValueError("nicht vollständig/außerhalb "
					f"Quellflächen: {measures}; "
					f"Toleranz {tolerance:.9f} m²")
			checks.append({
				"precision_grid_m":grid,
				"kontrollschnitt_m2":reference.area,
				"flaechenbilanz_voronoi_m2":balance_left,
				"flaechenbilanz_restmaske_m2":balance_right,
				"toleranz_m2":tolerance,
				**measures,
			})
		except (GEOSException,ValueError) as exc:
			failures.append(f"{grid:g} m: {exc}")
	if len(checks)!=2:
		raise ValueError(f"{label}: alternative Schnittberechnung "
			"nicht vollständig/außerhalb Quellflächen oder "
			"nicht unabhängig beweisbar: "+ " | ".join(failures))
	# Die beiden unabhängigen Referenzen dürfen untereinander
	# auch keine relevante Abweichung haben.
	ref_delta=abs(checks[0]["kontrollschnitt_m2"]-
		checks[1]["kontrollschnitt_m2"])
	ref_tol=min(checks[0]["toleranz_m2"],checks[1]["toleranz_m2"])
	if ref_delta>ref_tol:
		raise ValueError(f"{label}: Kontrollraster widersprechen "
			f"sich um {ref_delta:.9f} m², zulässig {ref_tol:.9f} m²")
	# Für bestehende Auswertungen die aggregierten alten Feldnamen
	# beibehalten, zusätzlich alle einzelnen Prüfraster protokollieren.
	measures={key:max(row[key] for row in checks) for key in (
		"ausserhalb_voronoi_zellen_m2",
		"ausserhalb_uebrigem_strassenraum_m2",
		"fehlend_von_voronoi_zellen_m2",
		"fehlend_vom_uebrigen_strassenraum_m2",
		"zusaetzlich_gegen_kontrollschnitt_m2")}
	measures["toleranz_m2"]=ref_tol
	measures["referenz_differenz_m2"]=ref_delta
	measures["kontrollraster"]=checks
	return measures

def _voronoi_intersection(owner_cells, remaining, cells, label,
	repair_events):
	"""Rekonstruktion nur wenn der normale Voronoi-Schnitt versagt.

	Zuerst jedes ursprüngliche Voronoi-Polygon separat schneiden.
	Im zweiten Schritt kleinste metrische Präzisionsraster testen.
	Beide Ersatzwege müssen die vollständige echte Schnittmenge
	der unveränderten Ausgangsgeometrien wiederherstellen.
	"""
	witnesses=(("Voronoi-Zellen",owner_cells),
		("noch nicht zugeordneter Straßenraum",remaining))
	if not owner_cells.is_valid or not remaining.is_valid:
		raise ValueError(f"{label}: ungültige Voronoi-/Straßenraum-"
			"Ausgangsgeometrie; keine automatische Schnittreparatur")
	try:
		raw=intersection(owner_cells,remaining)
		return _polygon(raw,label,witnesses=witnesses,
			repair_events=repair_events)
	except (ValueError,GEOSException) as original_error:
		original_error_message=str(original_error)
		failures=[]
		# Keine Flächen verschieben oder auf der ursprünglichen
		# ungültigen Intersection ein make_valid erzwingen.
		try:
			parts=[]
			for index,cell in enumerate(cells):
				local=intersection(cell,remaining)
				part=_polygon(local,f"{label}, Zelle {index}",
					witnesses=(("Voronoi-Einzelzelle",cell),
						("noch nicht zugeordneter Straßenraum",remaining)))
				if part is not None:
					parts.append(part)
			merged=union_all(parts) if parts else Polygon()
			candidate=_polygon(merged,f"{label}, Einzelzellen")
			checks=_check_overlay_intersection(
				candidate,owner_cells,remaining,label)
			method="Einzelzellen separat geschnitten und vereinigt"
			grid=None
		except (GEOSException,ValueError) as error:
			failures.append(f"Einzelzellen: {error}")
			candidate=None
			for precision in (1e-9,1e-8,1e-7,1e-6):
				try:
					raw=intersection(owner_cells,remaining,
						grid_size=precision)
					current=_polygon(raw,
						f"{label}, Präzision {precision:g} m")
					current_checks=_check_overlay_intersection(
						current,owner_cells,remaining,label)
					candidate=current
					checks=current_checks
					method="Voronoi-Overlay mit geprüftem Präzisionsraster"
					grid=precision
					break
				except (GEOSException,ValueError) as precision_error:
					failures.append(f"{precision:g} m: {precision_error}")
			if candidate is None:
				raise ValueError(f"{label}: Originalschnitt ungültig "
					f"({original_error}); auch Rekonstruktion und "
					"Präzisionsversuche nicht sicher: "
					+ " | ".join(failures)) from original_error
	event={
		"kontext":label,
		"methode":method,
		"originalfehler":original_error_message,
		"voronoi_einzelzellen":len(cells),
		"precision_grid_m":grid,
		"flaeche_m2":candidate.area if candidate is not None else 0.,
		"pruefung":checks,
	}
	repair_events.append(event)
	print(f"Partition-Hinweis: {label}: Schnitt aus "
		f"{len(cells)} Voronoi-Zellen neu aufgebaut ({method}); "
		f"Fläche {event['flaeche_m2']:.6f} m²; "
		"fehlend/außerhalb geprüft; "
		f"ursprünglicher Fehler: {original_error_message}")
	return candidate


def _rtree(db, table, bounds):
	x0,y0,x1,y1=bounds
	return db.execute(
		f"SELECT pk FROM {table} WHERE maxx>=? AND minx<=? AND maxy>=? AND miny<=?",
		(x0,x1,y0,y1))


def graph_context(db, bounds, *, halo=75):
	"""Nur benötigte Voronoi-Sites; Knotengrad aus GLOBALEN GIP-Achsen."""
	x0,y0,x1,y1=bounds
	search=(x0-halo,y0-halo,x1+halo,y1+halo)
	sx0,sy0,sx1,sy1=search
	# Eine räumliche SQL-Abfrage statt einer Abfrage je Stützpunkt:
	# bei Wien-weiten Millionen Stützpunkten entscheidend.
	rows=db.execute("""
		SELECT p.axis_pk,p.x,p.y
		FROM site_spatial s JOIN sites p ON p.pk=s.pk
		WHERE s.maxx>=? AND s.minx<=? AND s.maxy>=? AND s.miny<=?
		ORDER BY p.pk
	""",(sx0,sx1,sy0,sy1))
	sites=[(row["axis_pk"],row["x"],row["y"]) for row in rows]
	axis_ids={pk for pk,_,_ in sites}
	axes={}
	for pk in axis_ids:
		r=db.execute("SELECT pk,gip,name,fow,wkb FROM axes WHERE pk=?",(pk,)).fetchone()
		axes[pk]={"id":r["gip"],"name":r["name"],"fow":r["fow"],
			"geometry":loads(r["wkb"])}
	# Grad ausschließlich aus ALLEN geladenen Achsen, nicht aus
	# den in einer einzelnen Kachel sichtbaren Armen.
	# Das Gradverzeichnis wird bei der vollständigen Indexierung
	# EINMAL global erzeugt, nicht für jede Kachel neu gezählt.
	nodes=[]
	node_ids=[r[0] for r in _rtree(db,"node_spatial",
		(x0-7,y0-7,x1+7,y1+7))]
	for pk in node_ids:
		r=db.execute("SELECT gip,wkb FROM nodes WHERE pk=?",(pk,)).fetchone()
		degree=db.execute("SELECT degree FROM node_degrees WHERE gip=?",
			(r["gip"],)).fetchone()
		if degree and degree[0]>=3:
			nodes.append(loads(r["wkb"]))
	return sites,axes,nodes


def _empty_tile_stats():
	return {"strassenraum_m2":0., "zugeordnet_m2":0.,
		"ungeklaert_m2":0.,"fehlend_m2":0.,"overlap_m2":0.,
		"ausserhalb_m2":0.,"toleranz_m2":.05,
		"sites":0,"knoten":0,"geometrie_reparaturen":[]}


def split_tile(street, core, sites, axes, nodes,
	*, radius=7, max_distance=25, diagnostic=None, exclude_junctions=True, all_fow=False,
		junction_polygon=None):
	"""Identische Semantik zu V0, Voronoi-Sites aus globalem Index.

	Voraussetzung: halo >= max_distance + 5 + 7. Schnitt erfolgt
	im exakt definierten Kern, der pro Kachel disjunkt ist.
	"""
	if (not street.is_valid or not core.is_valid
		or not core.intersects(street)):
		if street.is_empty or not street.intersects(core):
			return {},{},_empty_tile_stats()
		raise ValueError("Straßenmaske oder Kachel ungültig")
	repair_events=[]
	mask=_polygon(street.intersection(core),"Straßenraum innerhalb Kachel",
		repair_events=repair_events)
	if mask is None:
		return {},{},_empty_tile_stats()
	junction=_polygon(junction_polygon.intersection(mask) if junction_polygon is not None
		else (union_all([node.buffer(radius,resolution=12) for node in nodes]).intersection(mask)
		if nodes and exclude_junctions else None),
		"Knotenbereich",repair_events=repair_events)
	remaining=mask.difference(junction) if junction is not None else mask
	assigned=defaultdict(list)
	special=[]
	# >=2 Sites sind nötig, wenn keine Achse die AOI beeinflusst,
	# wird alles ausdrücklich als Restfläche ausgewiesen.
	if len(sites)>MAX_SITES:
		raise ValueError(f"Über {MAX_SITES} Voronoi-Sites in einer Kachel: "
			"Kachelgröße reduzieren, NICHT den Abtastabstand verändern")
	if len(sites)>=2:
		pts=MultiPoint([(x,y) for _,x,y in sites])
		cells=voronoi_polygons(pts,extend_to=core.envelope.buffer(max_distance+10),
			ordered=True)
		if len(cells.geoms)!=len(sites):
			raise ValueError("Voronoi-Sites und -Zellen nicht bijektiv")
		by_axis=defaultdict(list)
		for cell,(pk,_,_) in zip(cells.geoms,sites):
			if cell.intersects(core):
				by_axis[pk].append(cell)
		# Jede Zelle gehört genau einem GIP-Abschnitt; Reihenfolge
		# ist nur für numerische Rundungsreste relevant.
		for pk in sorted(by_axis):
			axis=axes[pk]
			owner_cells=union_all(by_axis[pk])
			if diagnostic is not None:
				diagnostic(axis,owner_cells,remaining,by_axis[pk],mask,core)
			candidate=_voronoi_intersection(owner_cells,remaining,
				by_axis[pk],f"Voronoi {axis['id']}",repair_events)
			if candidate is None:
				continue
			axis_buffer=axis["geometry"].buffer(max_distance,resolution=8)
			near=_polygon(candidate.intersection(axis_buffer),
				f"Achsnähe {axis['id']}",
				witnesses=(("Voronoi-Anteil",candidate),
					("Achsabstand",axis_buffer)),
				repair_events=repair_events)
			if near is None:
				continue
			old_near=near
			near=_polygon(near.intersection(remaining),
				f"Exklusive Fläche {axis['id']}",
				witnesses=(("Achsnähe",old_near),
					("noch nicht zugeordneter Straßenraum",remaining)),
				repair_events=repair_events)
			if near is None:
				continue
			remaining=remaining.difference(near)
			if all_fow or axis["fow"]==3:
				assigned[axis["id"]].append(near)
			else:
				special.append(near)
	results={gid:_polygon(union_all(geoms),f"GIP {gid}",
		repair_events=repair_events)
		for gid,geoms in assigned.items()}
	unresolved={}
	if junction is not None:
		unresolved["knotenbereich"]=junction
	if special:
		unresolved["sonderachse"]=_polygon(union_all(special),"Sonderachsen",
			repair_events=repair_events)
	rest=_polygon(remaining,"nicht zugeteilt",
		repair_events=repair_events)
	if rest is not None:
		unresolved["nicht_zugeordnet"]=rest
	pieces=list(results.values())+list(unresolved.values())
	combined=union_all(pieces) if pieces else None
	sum_area=sum(g.area for g in pieces)
	overlap=max(0,sum_area-combined.area) if combined is not None else 0
	missing=mask.difference(combined).area if combined is not None else mask.area
	outside=combined.difference(mask).area if combined is not None else 0
	limit=max(.05,mask.area*1e-6)
	if max(overlap,missing,outside,abs(sum_area-mask.area))>limit:
		raise ValueError(f"V0-Kachelbilanz: fehlend {missing:.6f}, "
			f"Überlappung {overlap:.6f}, außerhalb {outside:.6f} m²")
	return results,unresolved,{
		"strassenraum_m2":mask.area,
		"zugeordnet_m2":sum(g.area for g in results.values()),
		"ungeklaert_m2":sum(g.area for g in unresolved.values()),
		"fehlend_m2":missing,"overlap_m2":overlap,
		"ausserhalb_m2":outside,"toleranz_m2":limit,
		"sites":len(sites),"knoten":len(nodes),
		"geometrie_reparaturen":repair_events,
	}


def connect_results(path, *, create=False):
	path=Path(path)
	if create:
		path.parent.mkdir(parents=True,exist_ok=True)
		if path.exists():
			raise FileExistsError(f"Ergebnisse existieren: {path}")
	with sqlite3.connect(path) as db:
		if create:
			db.executescript("""
				CREATE TABLE config(key TEXT PRIMARY KEY,value TEXT NOT NULL);
				CREATE TABLE tiles(id TEXT PRIMARY KEY,street_sha256 TEXT NOT NULL,
					area REAL NOT NULL,assigned REAL NOT NULL,
					unresolved REAL NOT NULL,elapsed_s REAL NOT NULL,
					stats_json TEXT NOT NULL);
				CREATE TABLE parts(tile_id TEXT NOT NULL,
					kind TEXT NOT NULL,gip_id TEXT NOT NULL,
					area REAL NOT NULL, geom BLOB NOT NULL,
					PRIMARY KEY(tile_id,kind,gip_id));
				CREATE INDEX parts_by_gid ON parts(gip_id);
			""")
	# sqlite connections cannot be returned via context manager above.
	return sqlite3.connect(path)


def write_tile(db, tile_id, street_sha, assignments, unresolved, stats, elapsed):
	if db.execute("SELECT 1 FROM tiles WHERE id=?",(tile_id,)).fetchone():
		raise FileExistsError(f"Ergebnis-Kachel existiert schon: {tile_id}")
	with db:
		db.execute("""INSERT INTO tiles VALUES (?,?,?,?,?,?,?)""",(
			tile_id,street_sha,stats["strassenraum_m2"],
			stats["zugeordnet_m2"],stats["ungeklaert_m2"],elapsed,
			json.dumps(stats,ensure_ascii=False)))
		for kind,mapping in (("abschnitt",assignments),("ungeklaert",unresolved)):
			for gid,geom in mapping.items():
				if geom is None or not geom.is_valid or geom.area<=0:
					raise ValueError(f"Ungültiger Ergebnisteil {tile_id}:{kind}:{gid}")
				db.execute("INSERT INTO parts VALUES (?,?,?,?,?)",(
					tile_id,kind,gid,geom.area,dumps(geom)))


def report_results(db, manifest):
	items=db.execute("SELECT id,area,assigned,unresolved,elapsed_s FROM tiles").fetchall()
	ids={row[0] for row in items}
	expected={t["id"] for t in manifest["tiles"]}
	if ids!=expected:
		raise ValueError(f"Unvollständiger Wien-Lauf: "
			f"{len(expected-ids)} Kacheln fehlen, {len(ids-expected)} unerwartet")
	area=sum(r[1] for r in items)
	assigned=sum(r[2] for r in items)
	unresolved=sum(r[3] for r in items)
	# Kacheln sind disjunkt; Flächenbeiträge werden je GIP-ID
	# zusammengefasst, ohne Geometrie über die Kachel hinweg
	# im Speicher vereinigen zu müssen.
	groups=db.execute("""
		SELECT kind,gip_id,COUNT(*),SUM(area)
		FROM parts GROUP BY kind,gip_id ORDER BY kind,gip_id
	""").fetchall()
	tot=assigned+unresolved
	if abs(tot-area)>max(.05,area*1e-6):
		raise ValueError(f"Wienweite Ergebnisbilanz fehlerhaft: {tot-area} m²")
	return {"schema_version":SCHEMA,"status":"vorläufige V0-Aufteilung; "
		"keine fachlich geprüfte Straßenabgrenzung",
		"kacheln":len(items),"strassenraum_m2":area,
		"abschnitte_m2":assigned,"ungeklaert_m2":unresolved,
		"bilanzdifferenz_m2":tot-area,
		"geometrisch_eindeutige_gip_ids":sum(1 for r in groups if r[0]=="abschnitt"),
		"klassengruppen":{key:sum(r[3] for r in groups
			if r[0]=="ungeklaert" and r[1]==key) for key in GROUPS},
		"laufzeit_s":sum(r[4] for r in items),
		"hinweis":"Kachelgrenzen nur rechnerische Arbeitsbereiche; jede "
			"GIP-ID bleibt über sämtliche Kacheln identisch. "
			"Flächen sind ohne Überlagerung geschnitten.",
	}


def run(manifest_path, gip_path, street_root, output, *, limit_tiles=None,
		exclude_junctions=True, all_fow=False, gip2_hulls=False, gip2_local=False):
	manifest,aoi=read_manifest(manifest_path)
	street_root,output=Path(street_root),Path(output)
	from scripts.wienwide_street import load_street_tile
	with connect_gip(gip_path) as gip:
		metadata=dict((r["key"],json.loads(r["value"]))
			for r in gip.execute("SELECT key,value FROM meta"))
		_validate_index_metadata(metadata,checksum(manifest_path),
			gip2_hulls=gip2_hulls or gip2_local)
		tiles=manifest["tiles"]
		if limit_tiles is not None:
			if limit_tiles<1:raise ValueError("limit_tiles muss positiv sein")
			tiles=tiles[:limit_tiles]
		is_new=not output.exists()
		with connect_results(output,create=is_new) as target:
			orig_config=dict(target.execute("SELECT key,value FROM config"))
			expected={"manifest_sha256":checksum(manifest_path),
				"gip_sha256":checksum(gip_path),"schema_version":str(SCHEMA)}
			if not exclude_junctions:
				expected["junction_policy"]="none"
			if all_fow:
				expected["fow_policy"]="all"
			if gip2_hulls:
				expected["junction_policy"]="gip2-turn-use-convex-hull"
			if not orig_config:
				with target:
					for key,value in expected.items():
						target.execute("INSERT INTO config VALUES (?,?)",(key,value))
			elif orig_config!=expected:
				raise ValueError("Bestehende Ausgabe gehört zu anderen GIP/AOI-Quellen")
			for i,tile in enumerate(tiles,1):
				source=street_root/tile["id"]/"street.sqlite"
				if not source.is_file():
					raise FileNotFoundError(f"Metrische Straßenraumkachel fehlt: {source}")
				sha=checksum(source)
				existing=target.execute("SELECT street_sha256 FROM tiles WHERE id=?",
					(tile["id"],)).fetchone()
				if existing:
					if existing[0]!=sha:
						raise ValueError(f"Geänderte Straßenraumquelle für {tile['id']}")
					print(f"Überspringe bereits geprüfte Kachel {tile['id']}")
					continue
				start=perf_counter()
				core=box(*tile["bounds_31256"]).intersection(aoi)
				street=load_street_tile(source,core)
				sites,axes,nodes=graph_context(gip,tile["bounds_31256"],
					halo=manifest["halo_m"])
				junction_polygon=None
				if gip2_hulls:
					bounds=core.bounds
					from shapely import union_all
					from shapely.wkb import loads
					hulls=[loads(r[0]) for r in gip.execute("""
						SELECT j.geom FROM junctions j JOIN junction_spatial s ON s.pk=j.rowid
						WHERE s.maxx>=? AND s.minx<=? AND s.maxy>=? AND s.miny<=?""",
						(bounds[0],bounds[2],bounds[1],bounds[3]))]
					junction_polygon=union_all(hulls) if hulls else None
				try:
					results,unknown,stats=split_tile(street,core,sites,axes,nodes,
						exclude_junctions=exclude_junctions and not gip2_hulls,
						all_fow=all_fow, junction_polygon=junction_polygon)
				except (ValueError,GEOSException) as exc:
					raise ValueError(f"{tile['id']}: {exc}") from exc
				elapsed=perf_counter()-start
				write_tile(target,tile["id"],sha,results,unknown,stats,elapsed)
				print(f"{i}/{len(tiles)} {tile['id']}: "
					f"{stats['strassenraum_m2']:.1f} m², "
					f"{stats['zugeordnet_m2']:.1f} m² zugeordnet, "
					f"{elapsed:.2f}s")
			count=target.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
			complete=count==len(manifest["tiles"])
			if complete:
				return _describe_method(report_results(target,manifest),
					gip2_hulls=gip2_hulls)
			return {"status":"PARTIELL – NICHT WIENWEIT VOLLSTÄNDIG",
				"fertige_kacheln":count,"gesamt_kacheln":len(manifest["tiles"])}


def main():
	p=argparse.ArgumentParser(description=__doc__)
	p.add_argument("--manifest",type=Path,required=True)
	p.add_argument("--gip-index",type=Path,required=True)
	p.add_argument("--street-root",type=Path,required=True)
	p.add_argument("--out",type=Path,required=True)
	p.add_argument("--limit-tiles",type=int,help="Begrenzter Diagnoselauf")
	p.add_argument("--gip2-local",action="store_true",
		help="Lokaler GIP2-EDGE-Index ohne Kreuzungsausschnitt")
	p.add_argument("--gip2-hulls",action="store_true",
		help="Kreuzungsausschluss aus lokalen GIP2 NODE/TURN_USE-Hüllen")
	p.add_argument("--all-fow",action="store_true",
		help="Alle GIP-Achsen unabhängig von FOW zuordnen")
	p.add_argument("--no-junctions",action="store_true",
		help="Nur Voronoi: keine Kreuzungsflächen abziehen")
	args=p.parse_args()
	try:
		report=run(args.manifest,args.gip_index,args.street_root,args.out,
			limit_tiles=args.limit_tiles, exclude_junctions=not args.no_junctions, all_fow=args.all_fow,
			gip2_hulls=args.gip2_hulls, gip2_local=args.gip2_local)
		print(json.dumps(report,ensure_ascii=False,indent=2))
	except (OSError,ValueError,TypeError,KeyError,sqlite3.Error) as exc:
		p.exit(1,f"Fehler: {exc}\n")


if __name__=="__main__":
	main()
