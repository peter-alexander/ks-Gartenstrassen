"""Stream and validate the native CGAL edge -> two generator sites format.

The E header belongs to the following (possibly empty) S/R/L fragments.
This keeps the dual-edge topology instead of guessing ownership from
post-polygonized representative points.
"""
from pathlib import Path
import math


def _site(text):
	fields=text.split()
	if fields[0]=="P" and len(fields)==3:
		pass
	elif fields[0]=="S" and len(fields)==5:
		pass
	else:
		raise ValueError("Ungültige CGAL-Generator-Site")
	values=tuple(float(v) for v in fields[1:])
	if not all(math.isfinite(v) for v in values):
		raise ValueError("Nicht endliche Generator-Site")
	return fields[0],values


def labelled_edges(lines):
	seen=False
	index=-1
	sites=None
	fragments=[]
	for lineno,line in enumerate(lines,1):
		parts=line.strip().split()
		if not parts:
			continue
		if parts[0]=="E":
			if seen:
				yield index,sites,fragments
			site_text=line.strip().split(" | ")
			fields=site_text[0].split(maxsplit=2)
			if len(site_text)!=2 or len(fields)!=3:
				raise ValueError(f"CGAL-E-Zeile {lineno} ungültig")
			next_index=int(fields[1])
			if next_index!=index+1:
				raise ValueError(f"CGAL-E-Zeile {lineno}: ID nicht fortlaufend")
			index=next_index
			sites=(_site(fields[2]),_site(site_text[1]))
			fragments=[]
			seen=True
		elif parts[0] in ("S","R","L") and len(parts)==5 and seen:
			coords=tuple(float(v) for v in parts[1:])
			if not all(math.isfinite(v) for v in coords):
				raise ValueError(f"CGAL-Zeile {lineno}: nicht endliche Koordinaten")
			fragments.append((parts[0],coords))
		else:
			raise ValueError(f"CGAL-Zeile {lineno}: ungültige Reihenfolge/Format")
	if seen:
		yield index,sites,fragments


def labelled_edges_file(path):
	with Path(path).open(encoding="utf-8") as stream:
		yield from labelled_edges(stream)
