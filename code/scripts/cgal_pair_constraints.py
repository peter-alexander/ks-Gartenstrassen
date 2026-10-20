"""Experimental finite-domain constraint audit for unresolved CGAL face pairs.

Native generator pairs are equality constraints across shared edges:
opposite faces must take the two distinct sites. Proven neighbors are
fixed. A solution is reported only after enumerating all possibilities.
This never mutates reconstruction labels.
"""
from scripts.cgal_directed_boundary_audit import directed_face_edges


def _site(data):
	return (data["kind"],tuple(data["coordinates"]))


def audit_pair_constraints(polygons,labels,segments,*,tolerance=1e-8):
	unknown=[i for i,label in enumerate(labels) if label is None]
	records=directed_face_edges(polygons,labels,segments,
		face_ids=unknown,tolerance=tolerance,limit=100000)
	constraints={}
	for record in records:
		i=record["face_index"]
		for edge in record["reported_edges"]:
			sites=frozenset(_site(s) for s in edge["sites"])
			for neighbor in edge["neighbor_faces"]:
				j=neighbor["face_index"]
				key=(min(i,j),max(i,j))
				constraints.setdefault(key,set()).add(sites)
	adjacency={i:set() for i in unknown}
	for (i,j),pairs in constraints.items():
		if i in adjacency and j in adjacency:
			adjacency[i].add(j)
			adjacency[j].add(i)
	components=[]
	seen=set()
	for i in unknown:
		if i in seen:
			continue
		stack=[i]
		component=set()
		while stack:
			node=stack.pop()
			if node in component:
				continue
			component.add(node)
			stack.extend(adjacency[node]-component)
		seen.update(component)
		components.append(sorted(component))
	out=[]
	for component in components:
		borders=[(i,j,pairs) for (i,j),pairs in constraints.items()
			if i in component or j in component]
		domains={}
		for node in component:
			incident=[set(pair) for a,b,pairs in borders
				if node in (a,b) for pair in pairs]
			domains[node]=set.intersection(*incident) if incident else set()
		for i,j,pairs in borders:
			if i in component and j in component:
				continue
			node=i if i in component else j
			known=j if i==node else i
			if labels[known] is None:
				continue
			allowed=set.intersection(*(set(pair)-{labels[known]}
				if labels[known] in pair else set() for pair in pairs))
			domains[node].intersection_update(allowed)
		solutions=[]
		def search(remaining,assigned):
			if len(solutions)>=2:
				return
			if not remaining:
				solutions.append(dict(assigned))
				return
			node=min(remaining,key=lambda k:len(domains[k]))
			for site in sorted(domains[node],key=repr):
				ok=True
				for i,j,pairs in borders:
					if node not in (i,j):
						continue
					other=j if i==node else i
					other_site=assigned.get(other,labels[other])
					if other_site is not None and all(
							{site,other_site}==pair for pair in pairs):
						continue
					if other_site is not None:
						ok=False
						break
				if ok:
					search([x for x in remaining if x!=node],
						{**assigned,node:site})
		search(component,{})
		out.append({"face_indices":component,
			"constraints":sum(len(p) for _,_,p in borders),
			"domain_sizes":{str(i):len(domains[i]) for i in component},
			"solution_count_capped_at_2":len(solutions),
			"unique_assignment":({
				str(i):{"kind":site[0],"coordinates":list(site[1])}
				for i,site in solutions[0].items()} if len(solutions)==1
				else None)})
	return out
