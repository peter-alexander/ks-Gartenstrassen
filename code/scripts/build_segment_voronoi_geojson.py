"""True Boost segment Voronoi cells, clipped to verified SIS street surfaces.

One diagram is calculated for the full AOI: tile borders never become sites.
Curved Boost edges are discretized only when serializing polygon boundaries.
No substitution of point-site Voronoi is permitted.
"""
import argparse
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile

from pyproj import Transformer
from shapely import union_all
from shapely.geometry import Polygon, box, mapping
from shapely.ops import transform
from shapely.wkb import loads

from scripts.segment_voronoi_engine import SCALE, _noded_segments
from scripts.wienwide_grid import read_manifest, checksum, load_aoi
from scripts.wienwide_street import load_street_tile


def _bounded_diagram(axes,extent,*,scale=SCALE):
	try:
		import pyvoronoi
	except ImportError as exc:
		raise RuntimeError("pyvoronoi==1.2.8 fehlt") from exc
	segments,(ox,oy)=_noded_segments(axes,scale=scale)
	minx,miny,maxx,maxy=extent.bounds
	diameter=math.hypot(maxx-minx,maxy-miny)
	margin=max(1000.0,4*diameter)
	frame=[(minx-margin,miny-margin),(maxx+margin,miny-margin),
		(maxx+margin,maxy+margin),(minx-margin,maxy+margin)]
	pv=pyvoronoi.Pyvoronoi(scale)
	owners=[]
	for (a,b),owner in sorted(segments.items()):
		pv.AddSegment([[a[0]/scale,a[1]/scale],[b[0]/scale,b[1]/scale]])
		owners.append(owner)
	for a,b in zip(frame,frame[1:]+frame[:1]):
		pv.AddSegment([[a[0]-ox,a[1]-oy],[b[0]-ox,b[1]-oy]])
		owners.append(None)
	pv.Construct()
	return pv,owners,(ox,oy)


def _cell_polygon(pv,cell,edges,vertices,origin,*,curve_step_m=0.25):
	if cell.is_open:
		raise ValueError(f"Nicht geschlossene Voronoi-Zelle: {cell.site}")
	coords=[]
	for edge_index in cell.edges:
		edge=edges[edge_index]
		if edge.start<0 or edge.end<0:
			raise ValueError(f"Unendliche Kante in Zelle {cell.site}")
		start=vertices[edge.start]
		end=vertices[edge.end]
		if edge.is_linear:
			part=[(start.X,start.Y),(end.X,end.Y)]
		else:
			part=pv.DiscretizeCurvedEdge(edge_index,curve_step_m,1/SCALE)
			part=[tuple(pt[:2]) for pt in part]
			if not part:
				raise ValueError(f"Leere parabolische Kante in Zelle {cell.site}")
		if coords and math.dist(coords[-1],part[0])>0.01:
			raise ValueError(f"Unverbundene Kanten in Zelle {cell.site}")
		coords.extend(part[1:] if coords else part)
	if len(coords)<3:
		raise ValueError(f"Zelle {cell.site} ohne Polygonring")
	if math.dist(coords[-1],coords[0])>0.01:
		raise ValueError(f"Offener Polygonring in Zelle {cell.site}")
	coords[-1]=coords[0]
	polygon=Polygon([(x+origin[0],y+origin[1]) for x,y in coords])
	if polygon.is_empty or not polygon.is_valid:
		raise ValueError(f"Ungueltige Voronoi-Zelle {cell.site}")
	return polygon


def _street_mask(manifest_path,root,aoi_path):
	manifest,aoi=read_manifest(manifest_path)
	if checksum(aoi_path)!=manifest["aoi_sha256"]:
		raise ValueError("SIS- und LINEAR_USE-AOI stimmen nicht überein")
	parts=[]
	for tile in manifest["tiles"]:
		core=box(*tile["bounds_31256"]).intersection(aoi)
		street=load_street_tile(Path(root)/tile["id"]/"street.sqlite",core)
		if not street.is_empty:
			parts.append(street)
	if not parts:
		raise ValueError("SIS-Maske enthält keine Straßenflächen")
	mask=union_all(parts)
	if not mask.is_valid:
		raise ValueError("SIS-Straßenflächenunion ist ungültig")
	return mask


def _axes(path):
	with sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True) as db:
		rows=db.execute("SELECT edge_id,wkb FROM edge_axes ORDER BY edge_id").fetchall()
	if not rows:
		raise ValueError("LINEAR_USE-Cache enthält keine Achsen")
	return [(key,loads(blob)) for key,blob in rows]


def build(cache,aoi_path,sis_manifest,sis_root,out,*,curve_step_m=0.25):
	out=Path(out)
	if out.exists() or out.is_symlink():
		raise FileExistsError(out)
	if not math.isfinite(curve_step_m) or curve_step_m<=0:
		raise ValueError("Kurvendiskretisierung muss positiv und endlich sein")
	aoi=load_aoi(aoi_path)
	mask=_street_mask(sis_manifest,sis_root,aoi_path)
	axes=_axes(cache)
	pv,owners,origin=_bounded_diagram(axes,aoi)
	cells=pv.GetCells()
	edges=pv.GetEdges()
	vertices=pv.GetVertices()
	groups={}
	for i,cell in enumerate(cells):
		if cell.site<0 or cell.site>=len(owners):
			raise ValueError(f"Ungueltiger Boost-Site-Index {cell.site}")
		owner=owners[cell.site]
		if owner is None:
			continue
		polygon=_cell_polygon(pv,cell,edges,vertices,origin,
			curve_step_m=curve_step_m)
		if not polygon.intersects(mask):
			continue
		piece=polygon.intersection(mask)
		if piece.area>0:
			groups.setdefault(owner,[]).append(piece)
		if i%10000==0:
			print(f"Segment-Voronoi: {i}/{len(cells)} Zellen",flush=True)
	assigned=union_all([union_all(parts) for parts in groups.values()]) if groups else Polygon()
	missing=mask.difference(assigned).area
	tolerance=max(0.01,mask.area*1e-7)
	if missing>tolerance:
		raise ValueError(f"Segment-Voronoi hat SIS-Luecken von {missing:.3f} m2")
	overlap=sum(sum(p.area for p in parts) for parts in groups.values())-assigned.area
	if overlap>tolerance:
		raise ValueError(f"Segment-Voronoi hat ueberlappende SIS-Flaechen: {overlap:.3f} m2")
	out.parent.mkdir(parents=True,exist_ok=True)
	stage=None
	to_wgs=Transformer.from_crs(31256,4326,always_xy=True).transform
	try:
		with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=out.parent,
				prefix=out.name+".",suffix=".tmp",delete=False) as stream:
			stage=Path(stream.name)
			stream.write('{"type":"FeatureCollection","features":[')
			count=0
			for owner,parts in sorted(groups.items()):
				geom=union_all(parts)
				if not geom.is_valid:
					raise ValueError(f"Ungueltige Vereinigungsfläche: {owner}")
				if geom.area<=0:
					continue
				feature={"type":"Feature","properties":{"edge_id":owner,
					"area_m2":geom.area,"method":"boost_segment_voronoi",
					"curve_step_m":curve_step_m},
					"geometry":mapping(transform(to_wgs,geom))}
				if count:
					stream.write(",\n")
				stream.write(json.dumps(feature,ensure_ascii=False,
					separators=(",",":"),allow_nan=False))
				count+=1
			stream.write("]}\n")
		os.replace(stage,out)
		stage=None
	finally:
		if stage is not None:
			stage.unlink(missing_ok=True)
	print(json.dumps({"output":str(out),"features":count,
		"boost_cells":len(cells),"source_segments":len(owners)-4,
		"curve_step_m":curve_step_m},ensure_ascii=False,indent=2))
	return count


def main():
	parser=argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--cache",type=Path,required=True)
	parser.add_argument("--aoi",type=Path,required=True)
	parser.add_argument("--sis-manifest",type=Path,required=True)
	parser.add_argument("--sis-root",type=Path,required=True)
	parser.add_argument("--out",type=Path,required=True)
	parser.add_argument("--curve-step-m",type=float,default=0.25)
	args=parser.parse_args()
	build(args.cache,args.aoi,args.sis_manifest,args.sis_root,args.out,
		curve_step_m=args.curve_step_m)


if __name__=="__main__":
	main()
