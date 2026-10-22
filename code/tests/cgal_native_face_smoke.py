"""End-to-end native CGAL Voronoi_face -> edge_id polygon pre-SIS smoke."""
import sys
from pathlib import Path

from shapely.geometry import box

from scripts.cgal_native_faces import read_native_faces
from scripts.build_cgal_native_faces_pre_sis import _dissolve


def main(path):
	owners={
		((0,0),(20000,0)):"south",
		((0,10000),(20000,10000)):"middle",
		((0,20000),(20000,20000)):"north"}
	groups,stats=read_native_faces(Path(path),owners,(0,0),
		box(-5,-5,25,25))
	assert set(groups)=={"north","middle","south"},(stats,list(groups))
	assert stats["segment_faces_inside_window"]>=3,stats
	assert stats.get("frame_faces_omitted",0)==0,stats
	parts=list(_dissolve(groups))
	assert {owner for owner,_ in parts}==set(groups)
	assert sum(g.area for _,g in parts)>0
	print("CGAL native Voronoi faces smoke:",stats,
		"dissolved polygon groups:",len(parts))


if __name__=="__main__":
	main(sys.argv[1])
