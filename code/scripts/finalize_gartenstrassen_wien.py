"""Audit the completed Wien statistics GeoJSON and publish a PMTiles archive.

The analytical GeoJSON remains the authoritative product.  This module only
derives a presentation archive and small, reproducible completion records.
It deliberately never repairs, drops, or rewrites an analytical geometry.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile

from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform
from shapely.strtree import STRtree

from scripts.analyze_cgal_sis_grm import (
	_metric_geometry_for_statistics,_read_finished_metadata,_sis_features,
)
from scripts.wienwide_grid import checksum


SCHEMA="gartenstrassen-wien-finalization-v3"
REQUIRED_PERCENT_FIELDS=("boden_begruent_pct","grm2023_baumkronen_pct","vegetation_boden_oder_krone_pct")
LAYER="gartenstrassen_wien"
MAX_NUMERIC_ID=(1<<53)-1


def _implementation_digest():
	return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _feature_id(edge_id):
	"""Stable, JSON-safe numeric tile id while retaining the UUID property."""
	value=int.from_bytes(hashlib.sha256(edge_id.encode("utf-8")).digest()[:8],"big")
	return value & MAX_NUMERIC_ID


def _metadata_is_current(path,source_sha):
	if not Path(path).is_file():
		return False
	try:
		data=json.loads(Path(path).read_text(encoding="utf-8"))
	except (OSError,json.JSONDecodeError):
		return False
	return (data.get("schema")==SCHEMA
		and data.get("source_sha256")==source_sha
		and data.get("implementation_sha256")==_implementation_digest())


def _read_pmtiles_metadata(path):
	"""Small dependency-free PMTiles v3 header/metadata verification."""
	with Path(path).open("rb") as stream:
		header=stream.read(127)
		if len(header)!=127 or header[:7]!=b"PMTiles" or header[7]!=3:
			raise ValueError("keine PMTiles-v3-Datei")
		metadata_offset,metadata_length=struct.unpack_from("<QQ",header,24)
		compression=header[97]
		min_zoom,max_zoom=header[100],header[101]
		stream.seek(metadata_offset)
		payload=stream.read(metadata_length)
	if compression==2:
		payload=gzip.decompress(payload)
	elif compression!=1:
		raise ValueError(f"unbekannte PMTiles-Metadatenkompression {compression}")
	metadata=json.loads(payload)
	return {"minzoom":min_zoom,"maxzoom":max_zoom,"metadata":metadata}


def _verify_pmtiles(path,*,expected_features):
	if not Path(path).is_file() or Path(path).stat().st_size<512:
		raise ValueError("PMTiles-Ausgabe fehlt oder ist zu klein")
	info=_read_pmtiles_metadata(path)
	layers=info["metadata"].get("vector_layers",[])
	layer=next((item for item in layers if item.get("id")==LAYER),None)
	if layer is None:
		raise ValueError(f"PMTiles enthält keinen Layer {LAYER!r}")
	fields=layer.get("fields",{})
	missing={"edge_id","feature_id",*REQUIRED_PERCENT_FIELDS}.difference(fields)
	if missing:
		raise ValueError(f"PMTiles-Layer verliert notwendige Properties: {sorted(missing)}")
	if info["minzoom"]!=12 or info["maxzoom"]!=14:
		raise ValueError(f"PMTiles-Zoomgrenzen nicht 12–14: {info['minzoom']}–{info['maxzoom']}")
	return {"bytes":Path(path).stat().st_size,"minzoom":info["minzoom"],
		"maxzoom":info["maxzoom"],"layer":LAYER,
		"expected_features":expected_features,"fields":sorted(fields)}


def _audit_and_write_ndjson(source,ndjson):
	"""Audit all source features and write a PMTiles-only numeric-id stream."""
	to_metric=Transformer.from_crs(4326,31256,always_xy=True).transform
	geometries=[]
	edges=[]
	ids=set()
	report={"features":0,"unique_edge_ids":0,"metric_area_m2":0.,
		"boden_begruent_m2":0.,"grm2023_baumkronen_m2":0.,
		"baumkronen_ueber_begruentem_boden_m2":0.,
		"vegetation_boden_oder_krone_m2":0.,"invalid_source_geometries":[],
		"metric_statistics_repaired_features":0,"duplicate_edge_ids":[],
		"numeric_id_collisions":[],"metric_property_area_delta_max_m2":0.}
	seen_edges=set()
	with Path(ndjson).open("w",encoding="utf-8") as writer:
		for feature in _sis_features(source):
			props=feature.get("properties") or {}
			edge_id=props.get("edge_id")
			if not isinstance(edge_id,str) or not edge_id:
				raise ValueError("Feature ohne originale edge_id")
			if edge_id in seen_edges:
				report["duplicate_edge_ids"].append(edge_id)
			else:
				seen_edges.add(edge_id)
			fid=_feature_id(edge_id)
			if fid in ids:
				report["numeric_id_collisions"].append(edge_id)
			ids.add(fid)
			geom=shape(feature["geometry"])
			if geom.is_empty or not geom.is_valid:
				report["invalid_source_geometries"].append(edge_id)
				continue
			raw_metric=transform(to_metric,geom)
			# Use the identical narrow CRS-roundtrip rule as the statistics
			# phase.  The analytical WGS84 geometry is retained byte-for-byte.
			metric=_metric_geometry_for_statistics(feature,to_metric,edge_id)
			if not raw_metric.is_valid:
				report["metric_statistics_repaired_features"]+=1
			area=metric.area
			property_area=props.get("area_m2")
			if not isinstance(property_area,(int,float)):
				raise ValueError(f"{edge_id}: area_m2 fehlt")
			delta=abs(area-property_area)
			report["metric_property_area_delta_max_m2"]=max(
				report["metric_property_area_delta_max_m2"],delta)
			if delta>.1:
				raise ValueError(f"{edge_id}: area_m2 weicht um {delta:.6f} m² ab")
			for name in ("boden_begruent_m2","grm2023_baumkronen_m2",
					"baumkronen_ueber_begruentem_boden_m2",
					"vegetation_boden_oder_krone_m2"):
				value=props.get(name)
				if not isinstance(value,(int,float)) or value<-.01 or value>area+.1:
					raise ValueError(f"{edge_id}: ungültige Kennzahl {name}")
				report[name]+=value
			covered=(props["boden_begruent_m2"]+props["grm2023_baumkronen_m2"]
				-props["baumkronen_ueber_begruentem_boden_m2"])
			if abs(covered-props["vegetation_boden_oder_krone_m2"])>.1:
				raise ValueError(f"{edge_id}: Vegetations-Überlappungsbilanz ungültig")
			for pct_field,area_field in (("boden_begruent_pct","boden_begruent_m2"),
					("grm2023_baumkronen_pct","grm2023_baumkronen_m2"),
					("vegetation_boden_oder_krone_pct","vegetation_boden_oder_krone_m2")):
				pct=props.get(pct_field)
				expected=100*props[area_field]/area if area>0 else 0.
				if not isinstance(pct,(int,float)) or not 0<=pct<=100.0001 or abs(pct-expected)>.01:
					raise ValueError(f"{edge_id}: Prozentkennzahl fehlt oder ist falsch: {pct_field}")
			report["features"]+=1
			report["metric_area_m2"]+=area
			geometries.append(metric)
			edges.append(edge_id)
			output={"type":"Feature","id":fid,
				"properties":{**props,"feature_id":fid},"geometry":feature["geometry"]}
			writer.write(json.dumps(output,ensure_ascii=False,separators=(",",":"))+"\n")
	if report["invalid_source_geometries"]:
		raise ValueError("ungültige analytische Geometrien im Endprodukt")
	if report["duplicate_edge_ids"] or report["numeric_id_collisions"]:
		raise ValueError("nicht eindeutige edge_id oder PMTiles-ID im Endprodukt")
	report["unique_edge_ids"]=len(seen_edges)
	tree=STRtree(geometries)
	overlaps=[]
	for i,geom in enumerate(geometries):
		for candidate in tree.query(geom,predicate="intersects"):
			j=int(candidate)
			if j<=i:
				continue
			area=geom.intersection(geometries[j]).area
			if area>.01:
				overlaps.append((edges[i],edges[j],area))
	report["positive_area_overlaps_count"]=len(overlaps)
	report["positive_area_overlaps_m2"]=sum(row[2] for row in overlaps)
	report["largest_positive_area_overlaps"]= [
		{"edge_id_a":a,"edge_id_b":b,"area_m2":area}
		for a,b,area in sorted(overlaps,key=lambda row:row[2],reverse=True)[:20]
	]
	if overlaps:
		raise ValueError("positive Flächenüberlappungen zwischen finalen edge_ids")
	return report


def finalize(source,pmtiles,metadata,report,*,replace_existing=False):
	source,pmtiles,metadata,report=map(Path,(source,pmtiles,metadata,report))
	if not source.is_file():
		raise FileNotFoundError(source)
	source_meta=_read_finished_metadata(source)
	# The statistics phase currently publishes v1.  Finalization must consume
	# that exact terminal contract; accepting a newer, unwritten schema here
	# made every otherwise complete production run fail at the last stage.
	if source_meta.get("schema")!="cgal-sis-grm-ground-v1":
		raise ValueError("Finalisierung benötigt CGAL/SIS/GRM-Statistik-GeoJSON")
	source_sha=checksum(source)
	if (not replace_existing and pmtiles.exists() and metadata.exists() and report.exists()
			and _metadata_is_current(metadata,source_sha)):
		_verify_pmtiles(pmtiles,expected_features=json.loads(metadata.read_text())["features"])
		return {"status":"cached","source_sha256":source_sha}
	if any(path.exists() for path in (pmtiles,metadata,report)) and not replace_existing:
		raise FileExistsError("Finale Ausgabe unvollständig oder veraltet; --replace-existing erforderlich")
	pmtiles.parent.mkdir(parents=True,exist_ok=True)
	with tempfile.TemporaryDirectory(dir=pmtiles.parent,prefix=".gartenstrassen-final-") as folder:
		folder=Path(folder)
		ndjson=folder/"features.ndjson"
		qa=_audit_and_write_ndjson(source,ndjson)
		stage_pmtiles=folder/pmtiles.name
		command=["tippecanoe","-o",str(stage_pmtiles),"--force","-l",LAYER,
			"--minimum-zoom=12","--maximum-zoom=14",
			"--full-detail=12","--low-detail=12",
			"--simplify-only-low-zooms","--no-tiny-polygon-reduction",
			"--no-feature-limit","--no-tile-size-limit",
			"--name","Wien Gartenstraßen – Begrünungsanalyse",str(ndjson)]
		subprocess.run(command,check=True)
		qa["pmtiles"]=_verify_pmtiles(stage_pmtiles,expected_features=qa["features"])
		final_meta={"schema":SCHEMA,"source":str(source),"source_sha256":source_sha,
			"implementation_sha256":_implementation_digest(),"features":qa["features"],
			"edge_id_property":"original edge_id; PMTiles feature_id is deterministic SHA-256/53-bit",
			"pmtiles":str(pmtiles),"quality_report":str(report)}
		for path,payload in ((folder/metadata.name,final_meta),(folder/report.name,qa)):
			path.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
		os.replace(stage_pmtiles,pmtiles)
		os.replace(folder/metadata.name,metadata)
		os.replace(folder/report.name,report)
	return {"status":"created",**final_meta}


def main():
	p=argparse.ArgumentParser(description=__doc__)
	p.add_argument("--source",type=Path,required=True)
	p.add_argument("--pmtiles",type=Path,required=True)
	p.add_argument("--metadata",type=Path,required=True)
	p.add_argument("--report",type=Path,required=True)
	p.add_argument("--replace-existing",action="store_true")
	a=p.parse_args()
	print(json.dumps(finalize(a.source,a.pmtiles,a.metadata,a.report,
		replace_existing=a.replace_existing),ensure_ascii=False,indent=2))


if __name__=="__main__":
	main()
