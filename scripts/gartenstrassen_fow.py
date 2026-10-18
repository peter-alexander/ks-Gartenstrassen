"""Conservative FORM_OF_WAY classification for Gartenstraßen.

Basis: GIP LUT lut_form_of_way_202607081451.csv (67 codes).
An explicit allowlist prevents unknown/new FOW values entering output.
This is a land-use *candidate* filter, not a statement of legal eligibility.
"""

# Road corridors that can independently be evaluated and published.
# 2: divided carriageway (not motorway)
# 3: undivided carriageway
# 14: pedestrian zone
STREET_FOW = frozenset((2, 3, 14))

# Nearby supporting infrastructure may be compared with a street corridor,
# but shall never become a stand-alone Gartenstraße candidate or PMTiles item.
# 15: footway; 504: shared foot/cycle path; 505: cycle path
SUPPORT_FOW = frozenset((15, 504, 505))
PARALLEL_FOW = STREET_FOW | SUPPORT_FOW


def fow_code(value):
	"""Return a strict integer GIP code or None (never infer missing codes)."""
	if type(value) is int:
		return value
	if isinstance(value, str) and value.isdecimal():
		return int(value)
	return None


def is_street_fow(value):
	return fow_code(value) in STREET_FOW


def is_parallel_fow(value):
	return fow_code(value) in PARALLEL_FOW


def is_street_pair(a, b):
	"""Compare two allowed axes only when at least one is a street corridor."""
	first, second = fow_code(a), fow_code(b)
	return first in PARALLEL_FOW and second in PARALLEL_FOW and (
		first in STREET_FOW or second in STREET_FOW)
