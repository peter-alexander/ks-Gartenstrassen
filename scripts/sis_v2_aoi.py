"""Erzeuge ein separates Pilot-AOI aus den SIS-Quellgeometrie-Bounds.

Das AOI ist der rechteckige Untersuchungsraum des gelieferten Testausschnitts;
es darf niemals als vollständige Wien-Grenze interpretiert werden.
"""
import argparse
import json
from pathlib import Path
import sqlite3

from pyproj import Transformer
from shapely.geometry import box, mapping
from shapely.ops import transform
from shapely.wkb import loads

TO_WGS = Transformer.from_crs("EPSG:31256","EPSG:4326",always_xy=True).transform


def run(database, output):
	output = Path(output)
	if output.exists():
		raise FileExistsError(output)
	with sqlite3.connect(f"file:{Path(database).resolve()}?mode=ro",uri=True) as db:
		meta = dict(db.execute("SELECT key,value FROM metadata"))
		if meta.get("provider") != "SISBELAGOGD":
			raise ValueError("Nicht der SIS-Datenprovider")
		row = db.execute("SELECT geom FROM street").fetchone()
		if row is None:
			raise ValueError("SIS-Straßenraum fehlt")
		union = loads(row[0])
		if not union.is_valid or union.is_empty:
			raise ValueError("SIS-Geometrie ungültig")
		aoi = transform(TO_WGS,box(*union.bounds))
		if not aoi.is_valid:
			raise ValueError("Pilot-AOI ungültig")
		output.parent.mkdir(parents=True,exist_ok=True)
		output.write_text(json.dumps(mapping(aoi))+"\n",encoding="utf-8")
		return {"datei":str(output),"bounds_4326":list(aoi.bounds)}


def main():
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("--sis-db",type=Path,required=True)
	p.add_argument("--out",type=Path,required=True)
	a = p.parse_args()
	print(json.dumps(run(a.sis_db,a.out),ensure_ascii=False,indent=2))


if __name__ == "__main__":
	main()
