"""Real CGAL A-B-C smoke: export point B but exclude endpoints A/C.

Input to CGAL:
	A=(0,0), B=(10,0), C=(15,12) metres, plus artificial frame.
This script verifies native point-site provenance and WGS84 GeoJSON
feature attributes from the real CGAL CCB output.
"""
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from shapely.geometry import LineString,box

from scripts.cgal_original_vertices import original_inner_point_owners
from scripts.cgal_native_face_preview import write_preview


def main(stream):
	lines=[("orig-1","abc",LineString([(0,0),(10,0),(15,12)]))]
	point_owners,stats=original_inner_point_owners(lines,(0,0))
	assert point_owners=={(10000,0):"abc"},point_owners
	owners={
		((0,0),(10000,0)):"abc",
		((10000,0),(15000,12000)):"abc"}
	raw=Path(stream).read_text(encoding="utf-8")
	assert "\nP 10000 0\n" in "\n"+raw,(
		"CGAL did not emit a bounded native point Face for the bent "
		"original vertex B")
	with TemporaryDirectory() as tmp:
		out=Path(tmp)/"preview.geojson"
		report=Path(tmp)/"report.json"
		summary=write_preview(stream,owners,(0,0),
			box(-30,-30,40,40),out,report,
			point_owners=point_owners)
		features=json.loads(out.read_text(encoding="utf-8"))["features"]
		segment=[f for f in features
			if f["properties"]["generator_type"]=="segment"]
		vertices=[f for f in features
			if f["properties"]["generator_type"]=="inner_point"]
		assert len(segment)==2,summary
		assert len(vertices)==1,(summary,vertices)
		assert all(f["properties"]["edge_id"]=="abc"
			for f in features),features
		assert summary["stats"]["point_faces_exported"]==1,summary
		assert summary["stats"][
			"point_faces_without_inner_original_vertex_omitted"]>=1,summary
		assert all(f["properties"]["preview_only"] is True
			for f in features)
		print("Real CGAL A-B-C: two segments, only original middle point "
			"B, all edge_id=abc; omitted endpoints",stats,summary["stats"])


if __name__=="__main__":
	main(Path(sys.argv[1]))
