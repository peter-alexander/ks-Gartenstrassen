"""Wienweiter GRM2023-Baumschicht-Provider, metrisch und kachelweise.

Nutzt den anhand der Legende bestätigten GRM2023OGD-WMS mit exakt
neun bekannten RGB-Klassen. Im Gegensatz zum Testausschnitt wird
das Gebiet in höchstens 500×500-m-GetMap-Anfragen (0,5 m/px) zerlegt.
Die Quelle ist eine gerenderte WMS-Baumschicht, KEIN amtliches
Baumkronen-Rohpolygon. Ohne vollständige valide PNG-Abdeckung
wird keine Kachel als abgeschlossen gespeichert.
"""
import argparse
from collections import Counter
from contextlib import closing
from io import BytesIO
import json
import math
import os
import tempfile
from pathlib import Path
import sqlite3
from time import sleep
from urllib.parse import quote

from PIL import Image
from shapely import union_all
from shapely.geometry import Polygon, box
from shapely.wkb import dumps,loads

from scripts.build_canopy_grm2023 import (
	CATEGORIES,TREE_RGB,polygonize_tree_pixels,
)
from scripts.probe_grm2023_wms import (
	get_map_url,parse_capabilities,request_bytes,require_png,wms_url,
)
from scripts.wienwide_grid import checksum,read_manifest

SCHEMA=1
PIXEL_M=.5
CHUNK_M=500
MAX_CHUNKS=1200  # Sicherheitsgrenze JE Rasterkachel, nicht für ganz Wien
MAX_REQUEST_BYTES=15_000_000


def chunks(tile,aoi):
	"""Räumlich feste, deckungsgleiche Kerne ohne Überlappung."""
	x0,y0,x1,y1=tile["bounds_31256"]
	core=box(x0,y0,x1,y1).intersection(aoi)
	if core.is_empty or core.area<=0:
		raise ValueError(f"{tile['id']}: leerer Arbeitskern")
	out=[]
	for iy in range(math.ceil((y1-y0)/CHUNK_M)):
		for ix in range(math.ceil((x1-x0)/CHUNK_M)):
			left=x0+ix*CHUNK_M
			bottom=y0+iy*CHUNK_M
			bounds=(left,bottom,min(left+CHUNK_M,x1),
				min(bottom+CHUNK_M,y1))
			if box(*bounds).intersection(core).area<=0:
				continue
			w=int(round((bounds[2]-bounds[0])/PIXEL_M))
			h=int(round((bounds[3]-bounds[1])/PIXEL_M))
			if (not 1<=w<=2048 or not 1<=h<=2048 or w*h>3_000_000
				or abs(bounds[0]+w*PIXEL_M-bounds[2])>1e-7
				or abs(bounds[1]+h*PIXEL_M-bounds[3])>1e-7):
				raise ValueError(f"{tile['id']}: unsicheres GetMap-Pixelraster")
			geo={"crs":"EPSG:31256","bbox":list(bounds),
				"width":w,"height":h}
			out.append((f"x{ix:03d}_y{iy:03d}",geo,get_map_url(geo)))
	if len(out)>MAX_CHUNKS:
		raise ValueError("Zu viele GRM-Anfragen je Kachel")
	# WMS-Anfragekacheln sind rechteckig. Am Bezirksrand decken sie
	# absichtlich auch den Bereich AUSSERHALB der AOI ab; gefordert
	# ist vollständige Bedeckung des Kerns, nicht Flächengleichheit.
	if core.difference(union_all([
		box(*geo["bbox"]) for _name,geo,_url in out])).area>max(.001,core.area*1e-9):
		raise ValueError(f"{tile['id']}: WMS-Kacheln decken den Kern nicht")
	return out


def chunk_paths(root,tile,name):
	folder=Path(root)/"png"/tile["id"]
	return folder/(name+".png"), folder/(name+".json")


def quarantine_chunk(root,tile,name,png,meta,*,reason):
	"""Bewahrt einen formal gültigen, fachlich aber unvollständigen Cache auf.

	Ein transparentes WMS-Bild innerhalb der AOI darf weder als Nullwert
	weiterverwendet noch kommentarlos überschrieben werden. Die Rohantwort und
	ihre Metadaten bleiben daher mit Prüfsumme und Fehlermeldung nachvollziehbar
	im Cache-Audit erhalten; der reguläre Pfad wird anschließend neu geladen.
	"""
	digest=checksum(png)
	dir=Path(root)/"ungueltige_wms_antworten"/tile["id"]
	dir.mkdir(parents=True,exist_ok=True)
	base=dir/f"{name}.{digest}"
	png.replace(base.with_suffix(".png"))
	meta.replace(base.with_suffix(".json"))
	(base.with_suffix(".audit.json")).write_text(json.dumps({
		"schema_version":1,
		"tile_id":tile["id"],
		"chunk":name,
		"png_sha256":digest,
		"grund":reason,
	},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
	return base


def verify_chunk(root,tile,name,geo,url):
	png,meta=chunk_paths(root,tile,name)
	if not png.is_file() or not meta.is_file():
		raise FileNotFoundError(f"{tile['id']}/{name}: GRM-Cache fehlt: {png}")
	report=json.loads(meta.read_text(encoding="utf-8"))
	if (report.get("schema_version")!=SCHEMA
		or report.get("tile_id")!=tile["id"]
		or report.get("raster")!=geo
		or report.get("getmap_url")!=url
		or report.get("png_sha256")!=checksum(png)
		or report.get("fachklasse")!=3
		or report.get("farb_rgb")!=list(TREE_RGB)):
		raise ValueError(f"{tile['id']}/{name}: GRM-Cache und Metadaten widersprechen sich")
	return png,report


def _verify_transparent_outside_aoi(pixels,geo,core,*,label):
	"""WMS-Hintergrund (transparentes Weiß) nur AUSSERHALB Wien erlauben.

	Ganzes 0,5-m-Pixelquadrat gegen die echte AOI schneiden.
	Ein Mittelpunkt-Test wäre an der Verwaltungsgrenze zu schwach.
	"""
	if core is None or core.is_empty or not core.is_valid:
		raise ValueError(f"{label}: Transparenz ohne gültige AOI "
			"nicht als fehlende Baumschicht klassifizieren")
	x0,y0,x1,y1=geo["bbox"]
	width,height=geo["width"],geo["height"]
	dx=(x1-x0)/width
	dy=(y1-y0)/height
	relevant=core.intersection(box(x0,y0,x1,y1))
	if relevant.is_empty or relevant.area<=0:
		raise ValueError(f"{label}: WMS-Teilbild liegt außerhalb der AOI")
	transparent=(255,255,255,0)
	count=0
	for row in range(height):
		start=None
		for x in range(width+1):
			is_nodata=x<width and pixels[row*width+x]==transparent
			if is_nodata:
				count+=1
				if start is None:
					start=x
			elif start is not None:
				pixel_run=box(x0+start*dx,y1-(row+1)*dy,
					x0+x*dx,y1-row*dy)
				if (pixel_run.intersects(relevant)
					and pixel_run.intersection(relevant).area>1e-9):
					raise ValueError(f"{label}: transparentes WMS-Weiß "
						"innerhalb Wiener AOI; kein nachgewiesener "
						f"GRM-Klassenwert (Zeile {row}, Pixel "
						f"{start} bis {x-1}); Baumschicht nicht "
						"als Null klassifizieren")
				start=None
	return count


def decode_chunk(png,geo,*,label,core=None):
	payload=Path(png).read_bytes()
	if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
		raise ValueError(f"{label}: WMS-Antwort ist kein PNG")
	with Image.open(BytesIO(payload)) as src:
		if src.format!="PNG" or src.size!=(geo["width"],geo["height"]):
			raise ValueError(f"{label}: falsches PNG-Format oder Rastermaß")
		src.load()
		pixels=list(src.convert("RGBA").getdata())
	freq=Counter(pixels)
	nodata=(255,255,255,0)
	unknown={str(rgb):n for rgb,n in freq.items()
		if rgb!=nodata and (rgb[3]!=255 or rgb[:3] not in CATEGORIES)}
	if unknown:
		raise ValueError(f"{label}: unbekannte/transparente WMS-Farben: "
			f"{list(unknown.items())[:8]}")
	transparent=freq.get(nodata,0)
	if transparent:
		checked=_verify_transparent_outside_aoi(pixels,geo,core,label=label)
		if checked!=transparent:
			raise ValueError(f"{label}: WMS-Transparenzzählung widersprüchlich")
	stats_base={"farben":{str(rgb):n for rgb,n in freq.items()},
		"transparente_pixel_ausserhalb_aoi":transparent}
	count=sum(n for rgb,n in freq.items()
		if rgb[:3]==TREE_RGB and rgb[3]==255)
	if not count:
		return Polygon(),{"baum_pixel":0,"baumschicht_m2":0,**stats_base}
	geom,stats=polygonize_tree_pixels(pixels,
		width=geo["width"],height=geo["height"],bbox=geo["bbox"])
	if count!=stats["baum_pixel"]:
		raise ValueError(f"{label}: Pixelzählung widersprüchlich")
	return geom,{"baum_pixel":count,"baumschicht_m2":geom.area,**stats_base}


def fetch(manifest_path,root,*,pause_s=.4):
	manifest,aoi=read_manifest(manifest_path)
	if not 0<=pause_s<=60:
		raise ValueError("pause_s außerhalb 0–60 s")
	all_chunks=[(tile,name,geo,url) for tile in manifest["tiles"]
		for name,geo,url in chunks(tile,aoi)]
	# Für Wien (489 Rasterkacheln) sind bei 500-m-Teilbildern bis
	# zu 4 × 489 GetMap-Aufrufe korrekt. Die sicherheitsrelevante
	# Grenze MAX_CHUNKS gilt weiterhin innerhalb jeder Kachel.
	# Gesamtzahl ist eine Fortschrittsangabe, keine Abbruchgrenze.
	print(f"GRM-Plan: {len(manifest['tiles'])} Kacheln, "
		f"{len(all_chunks)} WMS-Teilbilder (500 m, 0,5 m/Pixel)")
	# Prüft vorab den angegebenen amtlichen Layer und das metrische CRS.
	# Ein vollständig gecachter Lauf benötigt keine Netzverbindung.
	need_network=any(not chunk_paths(root,tile,name)[0].exists()
		and not chunk_paths(root,tile,name)[1].exists()
		for tile,name,geo,url in all_chunks)
	capabilities_checked=False
	def ensure_capabilities():
		nonlocal capabilities_checked
		if capabilities_checked:
			return
		caps=parse_capabilities(request_bytes(wms_url("GetCapabilities")),
			layer="GRM2023OGD")
		if "EPSG:31256" not in caps["unterstuetzte_srs"]:
			raise ValueError("GRM2023OGD unterstützt EPSG:31256 nicht")
		capabilities_checked=True
	if need_network:
		ensure_capabilities()
	results=[]
	quarantined=[]
	for index,(tile,name,geo,url) in enumerate(all_chunks,1):
		png,report=chunk_paths(root,tile,name)
		core=box(*tile["bounds_31256"]).intersection(aoi)
		if png.exists() or report.exists():
			cached,_=verify_chunk(root,tile,name,geo,url)
			try:
				decode_chunk(cached,geo,label=f"{tile['id']}/{name}",core=core)
			except ValueError as exc:
				quarantine_chunk(root,tile,name,cached,report,reason=str(exc))
				quarantined.append(f"{tile['id']}/{name}")
				print(f"GRM {index}/{len(all_chunks)}: ungültigen Cache "
					f"quarantiniert: {tile['id']}/{name}")
			else:
				continue
		# Nur zwischen tatsächlichen Netzabrufen drosseln.
		# Geprüfte Cache-Bilder erzeugen keine WMS-Last.
		if results and pause_s:
			sleep(pause_s)
		ensure_capabilities()
		payload=request_bytes(url,limit=MAX_REQUEST_BYTES)
		# WMS-Fehlerseiten werden verworfen; PNG wird streng validiert.
		require_png(payload,expected_size=(geo["width"],geo["height"]))
		png.parent.mkdir(parents=True,exist_ok=True)
		# Jede Anfrage bekommt eine eigene Temp-Datei im Zielverzeichnis.
		# Dadurch können fremde/abgebrochene .png.tmp-Dateien keinen
		# erfolgreichen Abruf mehr blockieren oder verschwinden lassen.
		temp=None
		try:
			with tempfile.NamedTemporaryFile(
					mode="wb",prefix=png.name+".",suffix=".tmp",
					dir=png.parent,delete=False) as target:
				temp=Path(target.name)
				target.write(payload)
			# Die Antwort vor der atomaren Veröffentlichung vollständig
			# klassifizieren; unvollständige WMS-Bilder dürfen nicht cachen.
			decode_chunk(temp,geo,label=f"{tile['id']}/{name}",core=core)
			os.replace(temp,png)
			d={"schema_version":SCHEMA,"tile_id":tile["id"],
				"raster":geo,"getmap_url":url,"png_sha256":checksum(png),
				"fachklasse":3,"farb_rgb":list(TREE_RGB),
				"hinweis":"GRM2023-GetMap-Rendering; nicht das amtliche Roh-Raster"}
			p=report.with_suffix(".json.tmp")
			p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n",
				encoding="utf-8")
			p.replace(report)
		except BaseException:
			if temp is not None:
				temp.unlink(missing_ok=True)
			raise
		results.append(f"{tile['id']}/{name}")
		print(f"GRM {index}/{len(all_chunks)}: {tile['id']}/{name}")
	return {"kacheln":len(manifest["tiles"]),"wms_bilder":len(all_chunks),
		"neu_geladen":len(results),"quarantaene":len(quarantined)}


def mask_path(root,tile):
	return Path(root)/"masken"/tile["id"]/"crown.sqlite"


def read_mask(root,tile,*,manifest,aoi,manifest_sha256=None):
	"""Validiert jedes Original-PNG gegen die fertige geometrische Maske."""
	path=mask_path(root,tile)
	if not path.is_file():
		raise FileNotFoundError(f"GRM-Baumschichtmaske fehlt: {path}")
	with closing(sqlite3.connect("file:"+quote(str(path.resolve()),safe="/")+
		"?mode=ro",uri=True)) as db:
		meta=dict(db.execute("SELECT key,value FROM metadata"))
		row=db.execute("SELECT geom FROM canopy").fetchone()
		if row is None:
			raise ValueError(f"{tile['id']}: Kronengeometrie fehlt")
	if meta.get("schema_version")!="1" or meta.get("crs")!="EPSG:31256":
		raise ValueError(f"{tile['id']}: ungültige GRM-Maskenmetadaten")
	if manifest_sha256 is None:
		manifest_sha256=checksum(manifest)
	if meta.get("manifest_sha256")!=manifest_sha256:
		raise ValueError(f"{tile['id']}: GRM-Maske gehört zu anderem Bezirksraster")
	original=json.loads(meta["png_sha256"])
	expected={}
	for name,geo,url in chunks(tile,aoi):
		png,_=verify_chunk(root,tile,name,geo,url)
		expected[name]=checksum(png)
	if original!=expected:
		raise ValueError(f"{tile['id']}: gespeicherte GRM-PNG-Herkunft geändert")
	geom=loads(row[0])
	core=box(*tile["bounds_31256"]).intersection(aoi)
	if (not geom.is_valid or geom.difference(core).area>.01
		or abs(geom.area-float(meta["baumschicht_m2"]))>.01):
		raise ValueError(f"{tile['id']}: GRM-Maske geometrisch ungültig")
	return geom,{"sha256":checksum(path),"baumschicht_m2":geom.area,
		"png_sha256":expected}


def build(manifest_path,root):
	manifest,aoi=read_manifest(manifest_path)
	completed=[]
	for i,tile in enumerate(manifest["tiles"],1):
		path=mask_path(root,tile)
		if path.exists():
			geom,_=read_mask(root,tile,manifest=manifest_path,aoi=aoi)
			print(f"GRM {i}/{len(manifest['tiles'])} {tile['id']}: "
				f"{geom.area:.1f} m² (geprüfter Cache)")
			completed.append(tile["id"])
			continue
		parts=[]
		digests={}
		tree_pixels=0
		outside_transparent_pixels=0
		core=box(*tile["bounds_31256"]).intersection(aoi)
		for name,geo,url in chunks(tile,aoi):
			png,_=verify_chunk(root,tile,name,geo,url)
			geom,stats=decode_chunk(png,geo,
				label=f"{tile['id']}/{name}",core=core)
			tree_pixels+=stats["baum_pixel"]
			outside_transparent_pixels+=stats["transparente_pixel_ausserhalb_aoi"]
			digests[name]=checksum(png)
			if not geom.is_empty:
				parts.append(geom)
		merged=union_all(parts) if parts else Polygon()
		if not merged.is_valid:
			raise ValueError(f"{tile['id']}: GRM-Baumschichtvereinigung ungültig")
		clipped=merged.intersection(core)
		if not clipped.is_valid or clipped.difference(core).area>.01:
			raise ValueError(f"{tile['id']}: Kronenfläche außerhalb Kachel")
		path.parent.mkdir(parents=True,exist_ok=True)
		# Ein abgebrochener Lauf darf die Wiederaufnahme nicht blockieren.
		# Eigenständiger Temp-Name im selben Verzeichnis ermöglicht atomaren
		# Abschluss; alte crown.sqlite.tmp-Dateien bleiben unangetastet.
		with tempfile.NamedTemporaryFile(
				prefix=path.name+".",suffix=".tmp",
				dir=path.parent,delete=False) as stage:
			temp=Path(stage.name)
		try:
			with sqlite3.connect(temp) as db:
				db.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
				db.execute("CREATE TABLE canopy(geom BLOB NOT NULL)")
				db.execute("INSERT INTO canopy VALUES (?)",(dumps(clipped),))
				data={"schema_version":"1","crs":"EPSG:31256",
					"manifest_sha256":checksum(manifest_path),
					"png_sha256":json.dumps(digests,sort_keys=True),
					"baumschicht_m2":repr(clipped.area),
					"baum_pixel":str(tree_pixels),
					"transparente_pixel_ausserhalb_aoi":
						str(outside_transparent_pixels)}
				db.executemany("INSERT INTO metadata VALUES (?,?)",data.items())
			temp.replace(path)
		except BaseException:
			temp.unlink(missing_ok=True)
			raise
		completed.append(tile["id"])
		print(f"GRM {i}/{len(manifest['tiles'])} {tile['id']}: "
			f"{clipped.area:.1f} m², {tree_pixels} Baumpixel, "
			f"{outside_transparent_pixels} transparente Pixel außerhalb AOI")
	return {"fertige_kacheln":len(completed)}


def main():
	p=argparse.ArgumentParser(description=__doc__)
	p.add_argument("action",choices=("fetch","build"))
	p.add_argument("--manifest",type=Path,required=True)
	p.add_argument("--root",type=Path,required=True)
	p.add_argument("--pause-s",type=float,default=.4)
	args=p.parse_args()
	try:
		report=(fetch(args.manifest,args.root,pause_s=args.pause_s)
			if args.action=="fetch" else build(args.manifest,args.root))
		print(json.dumps(report,ensure_ascii=False))
	except (OSError,ValueError,TypeError,KeyError,sqlite3.Error) as exc:
		p.exit(1,f"Fehler: {exc}\n")


if __name__=="__main__":
	main()
