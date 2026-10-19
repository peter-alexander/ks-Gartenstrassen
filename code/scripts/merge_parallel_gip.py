"""Conservative parallel GIP edge grouping BEFORE SIS/Voronoi assignment.

The original GIP2 GeoPackage and the derived source-index are always read-only.
The new spatial index retains every original 5-m site and its coordinates, but
points selected parallel members at ONE street representative/owner. Original
edge identities, individual geometries and the membership relation are retained
in the derived SQLite index for unambiguous provenance.

No invented midpoint, no dropping branches, no automatic transitive chaining.
An ambiguous foot/cycle edge remains its original independent edge.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sqlite3

from shapely.geometry import MultiLineString
from shapely.wkb import dumps, loads

from scripts.diagnose_parallel_gip import find_parallel_pairs, read_axes
from scripts.gartenstrassen_fow import STREET_FOW, SUPPORT_FOW
from scripts.wienwide_grid import checksum

SCHEMA = "parallel-gip-groups-v1"


def _normalized_name(name):
	return " ".join((name or "").strip().casefold().split())


def _primary_order(edge):
	# The longest road axis is the stable representative. An infrastructure
	# support line must never become the representative of a street group.
	return (-edge.geom.length, edge.id)


def plan_groups(axes, pairs):
	"""Return disjoint, directly evidenced star groups; reject ambiguous joins."""
	by_id = {a.id:a for a in axes}
	street = {a.id:a for a in axes if a.fow in STREET_FOW}
	support = {a.id:a for a in axes if a.fow in SUPPORT_FOW}
	eligible = set()
	for pair in pairs:
		a,b = pair["a"],pair["b"]
		if a not in by_id or b not in by_id:
			raise ValueError("Paralleldiagnose referenziert unbekannte GIP-ID")
		left,right = by_id[a],by_id[b]
		if a in street and b in street:
			# Pedestrian areas are distinct from vehicle carriageways;
			# same street NAME alone does not justify merging them.
			if (left.fow == 14) != (right.fow == 14):
				continue
			if not _normalized_name(left.name) or (
					_normalized_name(left.name) != _normalized_name(right.name)):
				continue
		elif a in support and b in support:
			continue
		eligible.add(frozenset((a,b)))
	neighbors_by_id = defaultdict(set)
	for edge in eligible:
		a,b=tuple(edge)
		neighbors_by_id[a].add(b)
		neighbors_by_id[b].add(a)
	assigned = set()
	groups = {}
	rejected_chains = 0
	for anchor in sorted(street.values(),key=_primary_order):
		if anchor.id in assigned:
			continue
		members = [anchor.id]
		neighbors = sorted((
			street[b] for b in neighbors_by_id[anchor.id]
			if b in street and b not in assigned
		),key=_primary_order)
		for child in neighbors:
			if child.id == anchor.id or child.id in assigned:
				continue
			# A connected component is NOT automatically a group. Require
			# positive parallel evidence between every pair of street members.
			if not all(frozenset((child.id,other)) in eligible
					for other in members):
				rejected_chains += 1
				continue
			members.append(child.id)
			assigned.add(child.id)
		if len(members)>1:
			groups[anchor.id] = members
		assigned.add(anchor.id)
	# A supporting foot/cycle edge may attach only if it has exactly one
	# directly supported street representative. At ambiguous junctions
	# it remains independent; no false merging into multiple streets.
	support_ambiguous = 0
	road_roots={gid:root for root,members in groups.items()
		for gid in members}
	for item in sorted(support.values(),key=lambda e:e.id):
		candidate_roots = {
			road_roots.get(gid,gid)
			for gid in neighbors_by_id[item.id] if gid in street
		}
		if len(candidate_roots)==1:
			root = next(iter(candidate_roots))
			groups.setdefault(root,[root]).append(item.id)
		elif len(candidate_roots)>1:
			support_ambiguous += 1
	return {root:tuple(sorted(members)) for root,members in sorted(groups.items())
		if len(members)>1}, {
		"rejected_chains":rejected_chains,
		"ambiguous_support":support_ambiguous,
		"candidate_parallel_pairs":len(pairs),
	}


def _lines(geom):
	if geom.geom_type=="LineString":
		return [geom]
	if geom.geom_type=="MultiLineString":
		return list(geom.geoms)
	raise ValueError("Parallele GIP-Achse hat keine Liniengeometrie")


def run(source, output, *, reuse=False):
	source,output = Path(source),Path(output)
	if source.resolve()==output.resolve():
		raise ValueError("Der ursprüngliche GIP-Index darf nicht überschrieben werden")
	if not source.is_file() or source.is_symlink():
		raise FileNotFoundError(f"GIP-Quellindex fehlt: {source}")
	if output.is_symlink():
		raise FileExistsError("Symlink statt abgeleitetem GIP-Index")
	if output.exists():
		if not reuse:
			raise FileExistsError(f"Abgeleiteter GIP-Graph existiert bereits: {output}")
		with sqlite3.connect(f"file:{output.resolve()}?mode=ro",uri=True) as previous:
			stored = {k:json.loads(v) for k,v in
				previous.execute("SELECT key,value FROM meta")}
			if (stored.get("graph_groups_schema") != SCHEMA
				or stored.get("source_index_sha256") != checksum(source)):
				raise ValueError("Vorhandene Gruppen gehören zu einem anderen GIP-Index")
			if previous.execute("PRAGMA quick_check").fetchone()[0]!="ok":
				raise ValueError("Gruppen-SQLite ist beschädigt")
		print("GIP-Graph: geprüften Gruppierungsindex wiederverwendet",flush=True)
		return stored
	if output.parent.is_symlink():
		raise ValueError("Kein Symlink als Zielverzeichnis")
	output.parent.mkdir(parents=True,exist_ok=True)
	temp = output.with_name(output.name+".tmp")
	if temp.exists() or temp.is_symlink():
		raise FileExistsError(temp)
	try:
		axes = read_axes(source)
		pairs,candidates = find_parallel_pairs(axes)
		groups,audit = plan_groups(axes,pairs)
		members = {member:root for root,items in groups.items() for member in items}
		by_id = {a.id:a for a in axes}
		with sqlite3.connect(f"file:{source.resolve()}?mode=ro",uri=True) as original, \
				sqlite3.connect(temp) as target:
			# Backup API is consistent and leaves original index untouched.
			original.backup(target)
			if target.execute("SELECT 1 FROM sqlite_master WHERE name='original_axes'").fetchone():
				raise ValueError("Quellindex wurde bereits vereinigt")
			meta = {key:json.loads(value) for key,value in
				target.execute("SELECT key,value FROM meta")}
			if meta.get("index_method")!="gip2-local-edge-turn-use-v1" or (
					meta.get("sampling_m")!=5 or meta.get("max_axis_distance_m")!=25):
				raise ValueError("Nur unveränderte GIP2-Indexmethodik mit 5-m-Sites zulässig")
			target.executescript("""
				CREATE TABLE original_axes AS SELECT * FROM axes;
				CREATE UNIQUE INDEX original_axes_gip ON original_axes(gip);
				CREATE TABLE merged_members(
					original_id TEXT PRIMARY KEY,
					representative_id TEXT NOT NULL,
					role TEXT NOT NULL,
					original_fow INTEGER,
					original_name TEXT NOT NULL);
				CREATE INDEX members_by_representative
					ON merged_members(representative_id);
				CREATE TABLE merged_groups(
					representative_id TEXT PRIMARY KEY,
					representative_wkb BLOB NOT NULL,
					member_count INTEGER NOT NULL);
			""")
			gid_pk = {gid:pk for pk,gid in target.execute("SELECT pk,gip FROM axes")}
			site_before=target.execute("SELECT COUNT(*) FROM sites").fetchone()[0]
			# Every original axis remains resolvable even when not merged.
			for pk,gid,name,fow in target.execute(
					"SELECT pk,gip,name,fow FROM original_axes ORDER BY pk"):
				root=members.get(gid,gid)
				role=("repraesentant" if root==gid and gid in groups
					else "mitglied" if root!=gid else "unveraendert")
				target.execute("INSERT INTO merged_members VALUES (?,?,?,?,?)",
					(gid,root,role,fow,name))
			with target:
				for root,ids in groups.items():
					if root not in gid_pk:
						raise ValueError(f"Unbekannte repräsentative GIP-ID: {root}")
					# All original 5-m sites survive, with identical XY
					# coordinates and their unchanged site_spatial entries.
					for member in ids:
						if member != root:
							target.execute("UPDATE sites SET axis_pk=? WHERE axis_pk=?",
								(gid_pk[root],gid_pk[member]))
					geometry = MultiLineString([
						line for member in ids for line in
							_lines(loads(target.execute(
								"SELECT wkb FROM original_axes WHERE gip=?",
								(member,)).fetchone()[0]))
					])
					if geometry.is_empty or not geometry.is_valid:
						raise ValueError(f"{root}: unzulässige Gruppenlinien")
					# MultiLineString describes the full group corridor;
					# the original street is its representative centre axis.
					target.execute("UPDATE axes SET wkb=? WHERE gip=?",
						(dumps(geometry),root))
					target.execute("INSERT INTO merged_groups VALUES (?,?,?)",
						(root,dumps(by_id[root].geom),len(ids)))
					for member in ids:
						if member!=root:
							target.execute("DELETE FROM axes WHERE gip=?",(member,))
				remaining=target.execute("SELECT COUNT(*) FROM axes").fetchone()[0]
				site_after=target.execute("SELECT COUNT(*) FROM sites").fetchone()[0]
				if site_after!=site_before:
					raise ValueError("Stützpunkte durch Graphvereinigung verändert")
				orphan=target.execute("""SELECT COUNT(*) FROM sites s
					LEFT JOIN axes a ON a.pk=s.axis_pk WHERE a.pk IS NULL""").fetchone()[0]
				if orphan:
					raise ValueError(f"{orphan} Voronoi-Sites ohne Zielkante")
				orig_total=target.execute("SELECT COUNT(*) FROM original_axes").fetchone()[0]
				mapped_total=target.execute("SELECT COUNT(*) FROM merged_members").fetchone()[0]
				if orig_total!=mapped_total or sum(len(v)-1 for v in groups.values())!=orig_total-remaining:
					raise ValueError("Original-IDs nicht bijektiv auf Vereinigungen abgebildet")
				updated={
					"graph_groups_schema":SCHEMA,
					"source_index_sha256":checksum(source),
					"original_axes":orig_total,
					"achsen":remaining,
					"voronoi_sites":site_after,
					"merged_groups":len(groups),
					"merged_member_axes":sum(len(v) for v in groups.values()),
					"parallel_candidates":candidates,
					**audit,
				}
				for key,value in updated.items():
					target.execute("INSERT OR REPLACE INTO meta VALUES (?,?)",
						(key,json.dumps(value,ensure_ascii=False)))
			if target.execute("PRAGMA quick_check").fetchone()[0]!="ok":
				raise ValueError("Vereinigter GIP-Index beschädigt")
		temp.replace(output)
		print(f"GIP-Graph: {len(groups)} Gruppen aus "
			f"{sum(len(v) for v in groups.values())} Originalkanten; "
			f"{site_after} globale 5-m-Sites unverändert",flush=True)
		return updated
	except BaseException:
		temp.unlink(missing_ok=True)
		raise


def main():
	p=argparse.ArgumentParser(description=__doc__)
	p.add_argument("--source-index",type=Path,required=True)
	p.add_argument("--out",type=Path,required=True)
	p.add_argument("--reuse",action="store_true")
	a=p.parse_args()
	print(json.dumps(run(a.source_index,a.out,reuse=a.reuse),ensure_ascii=False,indent=2))


if __name__=="__main__":
	main()
