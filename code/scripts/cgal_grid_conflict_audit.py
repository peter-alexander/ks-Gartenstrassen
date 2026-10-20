"""Read-only native CGAL audit for boundary pair conflicts at shared sites.

For each unresolved face, collect source dual labels touching its boundary,
separate point/segment generator identities, and identify shared endpoints.
Do not infer or change cell ownership.
"""
from collections import Counter
from shapely.geometry import Point

from scripts.cgal_unresolved_site_audit import _metric_site


def audit_conflicting_faces(polygons,labels,labelled_segments,*,scale=1000.,limit=20):
	if len(polygons)!=len(labels) or scale<=0 or limit<1:
		raise ValueError("Invalid conflict audit arguments")
	result=[]
	for face_index,(face,owner) in enumerate(zip(polygons,labels)):
		if owner is not None:
			continue
		boundary=face.boundary
		incident=[]
		for source_index,(line,pair) in enumerate(labelled_segments):
			overlap=boundary.intersection(line).length
			if overlap<=1e-8:
				continue
			incident.append((source_index,frozenset(pair),overlap))
		pairs={pair for _,pair,_ in incident}
		if len(pairs)<2:
			continue
		common=set.intersection(*(set(pair) for pair in pairs))
		if len(common)==1:
			continue
		counter=Counter(site for _,pair,_ in incident for site in pair)
		all_sites=sorted(counter,key=repr)
		segments=[site for site in all_sites if site[0]=="S"]
		points=[site for site in all_sites if site[0]=="P"]
		endpoints={}
		for site in points:
			point=_metric_site(site,scale)
			matches=[segment for segment in segments
				if point.distance(_metric_site(segment,scale))<=1e-8]
			if matches:
				endpoints[repr(site)]={"site":{"kind":site[0],
					"coordinates":list(site[1])},
					"incident_segments":len(matches)}
		result.append({"face_index":face_index,"area_m2":face.area,
			"boundary_pair_count":len(pairs),
			"common_generator_count":len(common),
			"point_site_count":len(points),
			"segment_site_count":len(segments),
			"point_segment_endpoint_relations":list(endpoints.values()),
			"most_frequent_sites":[{
				"site":{"kind":site[0],"coordinates":list(site[1])},
				"incident_fragments":count,
				"inside_face":face.contains(_metric_site(site,scale)),
				"site_distance_m":face.distance(_metric_site(site,scale))}
				for site,count in counter.most_common(limit)],
			"dual_examples":[{
				"source_index":i,"overlap_m":length,
				"sites":[{"kind":site[0],"coordinates":list(site[1])}
					for site in sorted(pair,key=repr)]}
				for i,pair,length in sorted(incident,
					key=lambda value:-value[2])[:limit]]})
	return result
