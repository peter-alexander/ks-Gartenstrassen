"""Publikations-PMTiles für SIS-V2 mit explizitem Abschnittsflächenfilter.

GIP-Auswertung bleibt vollständig; 100 m² sind nur Exportfilter.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from scripts.wienwide_grid import checksum


def run(source, output, *, min_area=100):
	source, output = Path(source), Path(output)
	if output.exists():
		raise FileExistsError(output)
	if not 0 <= min_area < 1_000_000:
		raise ValueError("Ungültige Mindestfläche")
	tool = shutil.which("tippecanoe")
	if not tool:
		raise FileNotFoundError("tippecanoe fehlt")
	doc = json.loads(source.read_text(encoding="utf-8"))
	if doc.get("type") != "FeatureCollection":
		raise ValueError("V2-Export muss GeoJSON FeatureCollection sein")
	items = doc.get("features")
	if not isinstance(items,list):
		raise ValueError("Ungültige Featureliste")
	selected = []
	for feature in items:
		props = feature["properties"]
		area = float(props["abschnitt_flaeche_m2"])
		if area >= min_area:
			if "sis_vegetation_pct" not in props or "sis_potentiell_unversiegelt_pct" not in props:
				raise ValueError("V2-SIS-Kennzahlen fehlen")
			selected.append(feature)
	if not selected:
		raise ValueError("Keine Features erfüllen Mindestfläche")
	output.parent.mkdir(parents=True,exist_ok=True)
	filtered = output.with_suffix(".filtered.geojson.tmp")
	staged = output.with_suffix(".tmp.pmtiles")
	if filtered.exists() or staged.exists():
		raise FileExistsError("Vorhandene temporäre Exportdatei")
	try:
		filtered.write_text(json.dumps({"type":"FeatureCollection","features":selected},
			ensure_ascii=False), encoding="utf-8")
		cmd = [tool, "-o", str(staged), "-l", "gartenstrassen_sis_v2",
			"-Z", "8", "-z", "17", "--force", str(filtered)]
		subprocess.run(cmd, check=True)
		if not staged.is_file() or staged.stat().st_size == 0:
			raise ValueError("Leere PMTiles-Ausgabe")
		staged.replace(output)
		return {"output":str(output),"gip_ids":len(selected),
			"omitted":len(items)-len(selected),"min_area_m2":min_area,
			"source_sha256":checksum(source),"pmtiles_sha256":checksum(output)}
	finally:
		filtered.unlink(missing_ok=True)
		staged.unlink(missing_ok=True)


def main():
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("--geojson",required=True,type=Path)
	p.add_argument("--out",required=True,type=Path)
	p.add_argument("--min-area-m2",type=float,default=100.)
	a = p.parse_args()
	print(json.dumps(run(a.geojson,a.out,min_area=a.min_area_m2),
		ensure_ascii=False,indent=2))


if __name__ == "__main__":
	main()
