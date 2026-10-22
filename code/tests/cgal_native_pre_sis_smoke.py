"""Native CGAL three-line smoke: sites -> real Voronoi polygons -> owners."""
from pathlib import Path
import sys

from shapely.geometry import box

from scripts.build_cgal_voronoi_geojson import _read_dual_lines,_polygon_candidates
from scripts.build_cgal_pre_sis import _group_before_sis
from scripts.cgal_site_ownership import (
	read_sites,attribute_faces,require_sound_attribution)


def main(dual_path,site_path):
	# Source was passed to CGAL as integer millimetre coordinates.
	owners={
		((0,0),(20000,0)):"south",
		((0,10000),(20000,10000)):"middle",
		((0,20000),(20000,20000)):"north"}
	window=box(-5,-5,25,25)
	lines,_=_read_dual_lines(dual_path,window,(0,0))
	polygons,_=_polygon_candidates(lines,window)
	segments,counts=read_sites(site_path,owners,(0,0))
	labels,stats=attribute_faces(polygons,segments,counts)
	require_sound_attribution(stats)
	pairs=list(_group_before_sis(polygons,labels))
	assert counts["native_point_sites_omitted"]>0,counts
	assert len(segments)==3,counts
	assert {owner for owner,_ in pairs}=={"north","middle","south"},stats
	assert stats["polygons_with_segment_edge_id"]>=3,stats
	assert stats["polygons_without_segment_edge_id"]>0,stats
	print("Native CGAL pre-SIS smoke:",counts,"groups:",len(pairs))


if __name__=="__main__":
	main(Path(sys.argv[1]),Path(sys.argv[2]))
