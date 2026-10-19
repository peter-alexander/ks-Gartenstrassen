# Wissenschaftliche Methodik – Wiener Gartenstraßen

## Aktueller methodischer Zwischenstand

Derzeit wird ausschließlich die **quellgebundene Vorbereitung** der Daten
durchgeführt. Eine neue Methode zur Bildung von Straßenabschnitten wird
anschließend separat entwickelt.

## Quellen und dauerhafte Aufbereitung

- **SIS (Stadt Wien):** WFS-Antworten werden unter
  `raw/sis/wfs-kacheln/` gespeichert. Der deduplizierte Wiener Index liegt
  in `cache/sis-wien.sqlite`.
- **SIS-Straßenraum:** Aus den geprüften SIS-Belagsflächen werden
  rasterweise Straßenraumpolygone unter
  `cache/wien/strassenraum/` erzeugt.
- **GRM2023:** WMS-PNGs werden mit Herkunftsmetadaten unter `raw/grm2023/`
  gespeichert. Daraus abgeleitete Kronenmasken liegen dauerhaft unter
  `cache/wien/masken/`.
- **Wien-AOI/Raster:** `cache/wien/aoi.geojson` und
  `cache/wien/raster.json` bilden den gemeinsamen räumlichen Vertrag.
- **Berechnung:** metrisch in EPSG:31256.

## Nicht mehr Teil der Methode

Die bisherige Verwendung von GIP-EDGE-, NODE- und TURN_USE-Daten ist
entfernt. Es gibt damit aktuell:

- keine GIP-basierte Abschnittsbildung,
- keine Voronoi-Zuordnung zu GIP-Achsen,
- keine Parallelkantenvereinigung,
- keine FOW-basierte Abschnittsauswahl,
- keine Knoten- oder Kreuzungsflächen,
- keine Querschnitts-Beschneidung,
- keine GIP-basierte QA oder Messausgabe.

SIS- und GRM-Daten werden nicht verändert, nur dauerhaft vorbereitet.
