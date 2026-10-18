"""Strikte Prüfung von GeoJSON-Koordinatenbezug (WGS84 lon/lat).

RFC 7946 kennt kein benutzerdefiniertes crs-Attribut. WFS-GeoJSON
(GeoJSON 2008) kann aber deklarierte WGS84/CRS84-Koordinaten enthalten.
Diese bekannten Deklarationen dürfen eingelesen werden, ohne das
Originaldokument zu verändern. Anderes CRS niemals stillschweigend raten.
"""

import re


def is_lonlat_crs(value):
	"""True für bekannte WGS84-(lon,lat)-Deklarationen, sonst False."""
	if not isinstance(value, str):
		return False
	name = value.strip().upper()
	if name in {
		"EPSG:4326",
		"CRS:84",
		"CRS84",
		"OGC:CRS84",
		"URN:OGC:DEF:CRS:OGC:1.3:CRS84",
		"URN:OGC:DEF:CRS:OGC::CRS84",
		"HTTP://WWW.OPENGIS.NET/DEF/CRS/OGC/1.3/CRS84",
		"HTTP://WWW.OPENGIS.NET/DEF/CRS/OGC/0/CRS84",
		"HTTP://WWW.OPENGIS.NET/GML/SRS/EPSG.XML#4326",
	}:
		return True
	if re.fullmatch(r"URN:OGC:DEF:CRS:EPSG:[^:]*:4326", name):
		return True
	if re.fullmatch(r"HTTPS?://WWW\.OPENGIS\.NET/DEF/CRS/EPSG/[^/]+/4326", name):
		return True
	return False


def require_geojson_lonlat(data, *, label="GeoJSON"):
	"""Akzeptiert fehlendes/null-crs und ausdrücklich dokumentiertes WGS84.

	Die Felder bleiben unverändert; ein vorhandenes anderes Koordinaten-
	system muss vom Nutzer vorher in EPSG:4326 konvertiert werden.
	"""
	if "crs" not in data or data["crs"] is None:
		return
	crs = data["crs"]
	if not isinstance(crs, dict) or crs.get("type") != "name":
		raise ValueError(f"{label}: unbekannte GeoJSON-crs-Deklaration {crs!r}; EPSG:4326 erforderlich")
	properties = crs.get("properties")
	name = properties.get("name") if isinstance(properties, dict) else None
	if not is_lonlat_crs(name):
		raise ValueError(f"{label}: nicht unterstütztes Quell-CRS {name!r}; EPSG:4326/CRS84 erforderlich")
