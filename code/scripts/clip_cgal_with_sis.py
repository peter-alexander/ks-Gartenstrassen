"""Final Wiener CGAL-area overlay with ALL SIS-Belagsflächen, by edge_id.

Use the existing finalized Vienna SIS WFS-derived RTree (not the small
SIS pilot), and the INTERNAL union of native CGAL Faces produced before
SIS by dissolve_cgal_preview. Preserve the existing debug output from
that earlier stage, unchanged. Keep only positive-area intersections,
retaining Polygon/MultiPolygon and the original edge_id. No SIS BELAG
or TYPE filtering. No geometry repair/ownership reassignment.

Streams the line-oriented dissolved GeoJSON without loading all Vienna
features into memory. Refuses incomplete SIS index and malformed
upstream results; writes the final GeoJSON atomically.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from urllib.parse import quote

from pyproj import Transformer
from shapely.geometry import Polygon,MultiPolygon,shape,mapping
from shapely.ops import transform

from scripts.sis_wien_source import mask as sis_mask


SCHEMA="cgal-native-faces-sis-belagsflaechen-wien-v1"
SIS_SCHEMAS=frozenset(("sis-wien-index-v4","sis-wien-index-v5"))


def _features(path):
	"""Read exactly our streamed pre-SIS FeatureCollection."""
	with Path(path).open("r",encoding="utf-8") as inp:
		if inp.readline().strip()!='{"type":"FeatureCollection","features":[':
			raise ValueError("SIS-Schnitt benötigt das zeilenweise CGAL-Dissolve-GeoJSON")
		metadata=None
		for number,line in enumerate(inp,2):
			raw=line.strip()
			if not raw:
				continue
			if raw.startswith('],"metadata":'):
				doc=json.loads('{"type":"FeatureCollection","features":[]'+raw[1:])
				metadata=doc.get("metadata")
				break
			try:
				feature=json.loads(raw[:-1] if raw.endswith(",") else raw)
			except json.JSONDecodeError as exc:
				raise ValueError(f"CGAL-Dissolve-Zeile {number}: ungültiges Feature") from exc
			if not isinstance(feature,dict) or feature.get("type")!="Feature":
				raise ValueError(f"CGAL-Dissolve-Zeile {number}: kein Feature")
			yield feature
		if not isinstance(metadata,dict):
			raise ValueError("CGAL-Dissolve-Ausgabe abgeschnitten (Metadata fehlt)")
		if not (str(metadata.get("schema","")).startswith(
				"cgal-original-edge-id-turn-use-hull-dissolve-")
				and metadata.get("dissolved_by")=="edge_id"):
			raise ValueError("Keine geprüfte finale CGAL-Dissolve-Eingabe")
		if inp.read().strip():
			raise ValueError("CGAL-Dissolve-Ausgabe enthält überzählige Daten")


def _validate_index(db):
	try:
		meta=dict(db.execute("SELECT key,value FROM metadata"))
		tables={name for (name,) in db.execute(
			"SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
	except sqlite3.Error as exc:
		raise ValueError("SIS-Wien-Index kann nicht gelesen werden") from exc
	if (meta.get("schema") not in SIS_SCHEMAS
			or meta.get("provider")!="SISBELAGOGD"
			or meta.get("crs")!="EPSG:31256"
			or not meta.get("sha256")):
		raise ValueError("SIS-Wien-Index unvollständig, veraltet oder falscher Provider")
	if not {"features","feature_index"}.issubset(tables):
		raise ValueError("SIS-Wien-Index ohne Features/RTree")
	if db.execute("SELECT COUNT(*) FROM features").fetchone()[0]==0:
		raise ValueError("SIS-Wien-Index ist leer")
	return meta


def _clip_feature(feature,db,to_metric,to_wgs,stats):
	props=feature.get("properties")
	if not isinstance(props,dict) or not isinstance(props.get("edge_id"),str) or not props["edge_id"]:
		raise ValueError("CGAL-Dissolve-Feature ohne originale edge_id")
	if props.get("sis_clipped") is not False:
		raise ValueError(f"{props['edge_id']}: SIS-Schnitt wurde bereits ausgeführt")
	geom=shape(feature.get("geometry"))
	if not isinstance(geom,(Polygon,MultiPolygon)) or geom.is_empty or not geom.is_valid:
		raise ValueError(f"{props['edge_id']}: ungültige polygonale CGAL-Eingabe")
	metric=transform(to_metric,geom)
	if not isinstance(metric,(Polygon,MultiPolygon)) or metric.is_empty or not metric.is_valid or metric.area<=0:
		raise ValueError(f"{props['edge_id']}: ungültige metrische CGAL-Eingabe")
	stats["pre_sis_area_sum_m2"]+=metric.area
	# Same proven SIS WFS-index RTree/geometry union used by the
	# existing SIS-V2 street mask, including ALL BELAG and TYPE values.
	clip=sis_mask(db,metric)
	if clip is None or clip.is_empty or clip.area<=0:
		stats["without_sis_overlap"]+=1
		return None
	if not isinstance(clip,(Polygon,MultiPolygon)) or not clip.is_valid:
		raise ValueError(f"{props['edge_id']}: ungültiger SIS-Polygonschnitt")
	# Guard area against accidental expansion / wrong mask.
	if clip.difference(metric).area>max(.01,metric.area*1e-9):
		raise ValueError(f"{props['edge_id']}: SIS-Ergebnis überschreitet ursprüngliche CGAL-Fläche")
	wgs=transform(to_wgs,clip)
	if not isinstance(wgs,(Polygon,MultiPolygon)) or wgs.is_empty or not wgs.is_valid:
		raise ValueError(f"{props['edge_id']}: ungültiger WGS84-SIS-Polygonschnitt")
	outprops=dict(props)
	outprops.update({
		"pre_sis_area_m2":metric.area,
		"area_m2":clip.area,
		"sis_clipped":True,
		"sis_provider":"SISBELAGOGD",
		"sis_mask":"all_belags_all_types",
	})
	stats["features_with_sis_overlap"]+=1
	stats["sis_overlap_area_sum_m2"]+=clip.area
	if isinstance(clip,MultiPolygon):
		stats["sis_multipolygon_features"]+=1
	return {"type":"Feature","properties":outprops,"geometry":mapping(wgs)}


def clip(pre_sis,sis_db,out,*,replace_existing=False,progress=None):
	pre_sis,sis_db,out=map(Path,(pre_sis,sis_db,out))
	if not pre_sis.is_file() or pre_sis.is_symlink():
		raise FileNotFoundError(f"CGAL-Dissolve-Eingabe fehlt: {pre_sis}")
	if not sis_db.is_file() or sis_db.is_symlink():
		raise FileNotFoundError(
			f"Wiener SIS-Index fehlt: {sis_db}. Zuerst "
			"bash code/scripts/run-sis-v2-wien.sh ausführen.")
	if out.is_symlink():
		raise ValueError(f"SIS-Ausgabe darf kein Symlink sein: {out}")
	if out.exists() and not replace_existing:
		raise FileExistsError(out)
	out.parent.mkdir(parents=True,exist_ok=True)
	if len({str(p.resolve()) for p in (pre_sis,sis_db,out)})!=3:
		raise ValueError("SIS-Eingaben und Ausgabe müssen verschieden sein")
	to_metric=Transformer.from_crs(4326,31256,always_xy=True).transform
	to_wgs=Transformer.from_crs(31256,4326,always_xy=True).transform
	stats=Counter()
	uri="file:"+quote(str(sis_db.resolve()),safe="/")+"?mode=ro"
	with sqlite3.connect(uri,uri=True) as db:
		meta=_validate_index(db)
		with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",
				dir=out.parent,prefix=out.name+".",suffix=".tmp",
				delete=False) as writer:
			stage=Path(writer.name)
			try:
				writer.write('{"type":"FeatureCollection","features":[\n')
				first=True
				for feature in _features(pre_sis):
					stats["pre_sis_features"]+=1
					clipped=_clip_feature(feature,db,to_metric,to_wgs,stats)
					if clipped is not None:
						if not first:
							writer.write(",\n")
						json.dump(clipped,writer,ensure_ascii=False,
							separators=(",",":"),allow_nan=False)
						first=False
					if progress and stats["pre_sis_features"]%1000==0:
						progress(
							f"SIS-Verschnitt: {stats['pre_sis_features']:,} "
							f"edge_ids, {stats['features_with_sis_overlap']:,} mit SIS-Fläche")
				writer.write('\n],"metadata":')
				json.dump({
					"schema":SCHEMA,
					"crs":"EPSG:4326",
					"metric_crs":"EPSG:31256",
					"sis_provider":"SISBELAGOGD",
					"sis_schema":meta["schema"],
					"sis_sha256":meta["sha256"],
					"sis_mask":"all_belags_all_types",
					"debug_stage":"after_turn_use_and_250m2_before_sis",
					"pre_sis_intermediate_not_published":True,
					"statistics":dict(stats),
					"preview_based":True,
				},writer,ensure_ascii=False,separators=(",",":"),
					allow_nan=False)
				writer.write("}\n")
				writer.flush()
				os.replace(stage,out)
			finally:
				stage.unlink(missing_ok=True)
	print(f"SIS-Verschnitt: {stats['pre_sis_features']:,} CGAL-edge_ids, "
		f"{stats['features_with_sis_overlap']:,} SIS-Flächen, "
		f"{stats['without_sis_overlap']:,} ohne Überdeckung, "
		f"{stats['sis_multipolygon_features']:,} MultiPolygone; "
		f"Ausgabe: {out}",flush=True)
	return dict(stats)


def main():
	p=argparse.ArgumentParser(description=__doc__)
	p.add_argument("--pre-sis",required=True,type=Path)
	p.add_argument("--sis-db",required=True,type=Path)
	p.add_argument("--out",required=True,type=Path)
	p.add_argument("--replace-existing",action="store_true")
	a=p.parse_args()
	clip(a.pre_sis,a.sis_db,a.out,replace_existing=a.replace_existing,
		progress=lambda message:print(message,flush=True))


if __name__=="__main__":
	main()
