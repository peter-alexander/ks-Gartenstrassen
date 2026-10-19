"""Strict provenance checks for durable derived Vienna cache files.

Never modify cached datasets. Reject legacy/unrelated partitions explicitly
instead of silently mixing them with the new parallel-GIP graph.
"""
import argparse
import json
from pathlib import Path
import sqlite3

from scripts.sis_v2_cross_sections import (
	STEP_M, WINDOW, TOLERANCE, MIN_GROWTH, MAX_SEARCH_M,
)
from scripts.wienwide_grid import checksum, read_manifest


def _meta(path, table):
	if not path.is_file() or path.is_symlink():
		raise FileNotFoundError(f"Cache-Datei fehlt: {path}")
	with sqlite3.connect(f"file:{path.resolve()}?mode=ro",uri=True) as db:
		if db.execute("PRAGMA quick_check").fetchone()[0]!="ok":
			raise ValueError(f"SQLite beschädigt: {path}")
		return dict(db.execute(f"SELECT key,value FROM {table}"))


def _partition(path, *, manifest_sha, gip_sha, final=False, tiles=None):
	record=_meta(path,"config")
	expected={"manifest_sha256":manifest_sha,"gip_sha256":gip_sha,
		"schema_version":"1","junction_policy":(
			"voronoi-stable-width-v1" if final else "none"),"fow_policy":"all"}
	for key,value in expected.items():
		if record.get(key)!=value:
			raise ValueError(
				f"{path}: {key} gehört nicht zur aktuellen GIP-/Rastermethode; "
				"den bestehenden Cache nicht überschreiben, alten Stand separat aufbewahren")
	if final:
		expected_rule={"step_m":STEP_M,"fenster":WINDOW,
			"toleranz":TOLERANCE,"mindestzunahme":MIN_GROWTH,
			"suchweite_m":MAX_SEARCH_M}
		if json.loads(record.get("querschnitt_regel","null"))!=expected_rule:
			raise ValueError(f"{path}: andere Querschnittsmethode im Cache")
	elif "querschnitt_regel" in record:
		raise ValueError(f"{path}: Rohpartition enthält bereits einen Querschnitt")
	if tiles is not None:
		with sqlite3.connect(f"file:{path.resolve()}?mode=ro",uri=True) as db:
			got=db.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
			if got!=tiles:
				raise ValueError(f"{path}: {got} statt {tiles} Rasterkacheln")
	return record


def verify(stage,cache,*,source=None,tile_m=1000):
	cache=Path(cache)
	if cache.is_symlink():
		raise ValueError("Wien-Cache darf kein Symlink sein")
	manifest_file=cache/"raster.json"
	manifest,aoi=read_manifest(manifest_file)
	if manifest["tile_size_m"]!=tile_m or manifest["halo_m"]!=75:
		raise ValueError("Gespeichertes Wien-Raster hat andere Kachelgröße/Halo")
	if stage=="grid":
		return {"stage":stage,"tiles":len(manifest["tiles"])}
	manifest_sha=checksum(manifest_file)
	gip=cache/"gip.sqlite"
	if stage=="gip":
		if source is None:
			raise ValueError("GIP-Quelldatei muss angegeben werden")
		meta={key:json.loads(value) for key,value in _meta(gip,"meta").items()}
		if (meta.get("manifest_sha256")!=manifest_sha
			or meta.get("index_method")!="gip2-local-edge-turn-use-v1"
			or meta.get("sampling_m")!=5
			or meta.get("max_axis_distance_m")!=25
			or meta.get("source_sha256")!=checksum(source)):
			raise ValueError(
				"Gespeicherter GIP-Index gehört zu anderem Quell-GPKG, "
				"Raster oder Verarbeitungsverfahren")
		return {"stage":stage,"axes":meta.get("achsen")}
	merged=cache/"gip_merged.sqlite"
	merged_sha=checksum(merged)
	if stage in ("trim","qa"):
		_partition(cache/"aufteilung_roh.sqlite",manifest_sha=manifest_sha,
			gip_sha=merged_sha,tiles=len(manifest["tiles"]))
		final=cache/"aufteilung.sqlite"
		_partition(final,manifest_sha=manifest_sha,gip_sha=merged_sha,
			final=True,tiles=len(manifest["tiles"]))
	if stage=="trim":
		return {"stage":stage,"graph_sha256":merged_sha}
	if stage=="qa":
		qa=cache/"qa.gpkg"
		provenance={key:json.loads(value) for key,value in
			_meta(qa,"qa_provenienz").items()}
		if (provenance.get("manifest_sha256")!=manifest_sha
			or provenance.get("gip_sha256")!=merged_sha
			or provenance.get("partition_sha256")!=checksum(final)
			or provenance.get("kacheln")!=len(manifest["tiles"])
			or provenance.get("schema_version")!=1):
			raise ValueError(
				"Gespeichertes QA-GeoPackage gehört zu anderem GIP-Graphen, "
				"Raster oder anderem Partitionsstand")
		return {"stage":stage,"tiles":provenance["kacheln"]}
	raise ValueError(f"Unbekannte Cache-Prüfung: {stage}")


def main():
	parser=argparse.ArgumentParser(description=__doc__)
	parser.add_argument("stage",choices=("grid","gip","trim","qa"))
	parser.add_argument("--cache",type=Path,required=True)
	parser.add_argument("--gip-source",type=Path)
	parser.add_argument("--tile-m",type=int,default=1000)
	args=parser.parse_args()
	print(json.dumps(verify(args.stage,args.cache,source=args.gip_source,
		tile_m=args.tile_m),ensure_ascii=False))


if __name__=="__main__":
	main()
