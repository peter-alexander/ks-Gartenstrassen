"""Publikations-PMTiles für SIS-V2 mit Gartenstraßen-FOW-Positivliste.

GIP-/QA-Auswertung bleibt vollständig; 100 m² und FOW gelten nur beim Export.
"""
import argparse
import hashlib
import uuid
import json
from pathlib import Path
import shutil
import subprocess

from scripts.wienwide_grid import checksum
from scripts.gartenstrassen_fow import is_street_fow, STREET_FOW


def run(source, output, *, min_area=100, replace=False):
	source, output = Path(source), Path(output)
	if output.exists() and not replace:
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
	excluded_fow = {}
	mvt_ids = set()
	for feature in items:
		props = feature["properties"]
		if not is_street_fow(props.get("fow")):
			code = str(props.get("fow"))
			excluded_fow[code] = excluded_fow.get(code, 0) + 1
			continue
		area = float(props["abschnitt_flaeche_m2"])
		if area >= min_area:
			if "boden_pct" not in props or "nicht_begruent_pct" not in props:
				raise ValueError("V2-SIS-Kennzahlen fehlen")
			gip_id = str(props.get("gip_id", ""))
			if gip_id.isdecimal() and 0 <= int(gip_id) < 2**63:
				mvt_id = int(gip_id)
			else:
				try:
					mvt_id = int.from_bytes(hashlib.sha256(uuid.UUID(gip_id).bytes).digest()[:8], "big") & ((1 << 63)-1)
				except (ValueError, AttributeError) as exc:
					raise ValueError(f"Ungültige GIP-UUID: {gip_id!r}") from exc
			if mvt_id in mvt_ids:
				raise ValueError(f"Kollision der numerischen MVT-ID für {gip_id}")
			mvt_ids.add(mvt_id)
			if str(feature.get("id")) != gip_id:
				raise ValueError(f"GeoJSON-ID und gip_id widersprechen sich: {feature.get('id')!r}/{gip_id!r}")
			# GeoJSON erlaubt String-IDs, Tippecanoe übernimmt als MVT-Feature-ID
			# aber nur Zahlen. Die Eigenschaft gip_id bleibt unverändert erhalten.
			selected.append({**feature, "id":mvt_id})
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
			"existing_replaced": bool(replace),
			"omitted":len(items)-len(selected),
			"omitted_fow":sum(excluded_fow.values()),
			"omitted_fow_by_code":dict(sorted(excluded_fow.items())),
			"omitted_min_area":len(items)-len(selected)-sum(excluded_fow.values()),
			"allowed_fow":sorted(STREET_FOW),"min_area_m2":min_area,
			"source_sha256":checksum(source),"pmtiles_sha256":checksum(output)}
	finally:
		filtered.unlink(missing_ok=True)
		staged.unlink(missing_ok=True)


def main():
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("--geojson",required=True,type=Path)
	p.add_argument("--out",required=True,type=Path)
	p.add_argument("--min-area-m2",type=float,default=100.)
	p.add_argument("--replace",action="store_true",
		help="Vorhandenes PMTiles erst nach erfolgreichem Neubau atomar ersetzen")
	a = p.parse_args()
	print(json.dumps(run(a.geojson,a.out,min_area=a.min_area_m2,
		replace=a.replace),
		ensure_ascii=False,indent=2))


if __name__ == "__main__":
	main()
