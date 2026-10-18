# Wissenschaftliche Methodik – Wiener Gartenstraßen

## Ziel

Flächendeckende GIS-Auswertung des Wiener Straßenraums als Grundlage zur
Identifikation bestehender Straßen mit Potenzial für Begrünungsmaßnahmen.
Die Berechnung ist eine explorative GIS-Analyse, keine rechtliche Einstufung
als Gartenstraße.

## Quellen und Koordinaten

- **SIS (Stadt Wien):** WFS-Antworten mit Belags- und TYPE-Attributen, komprimiert
  und samt Prüfsummen in `raw/sis/wfs-kacheln/` aufbewahrt.
- **GIP2:** `/mnt/c/Users/peter/Downloads/gip_network_ogd.gpkg`;
  die Layer EDGE, NODE und TURN_USE werden ausschließlich lesend aus dem
  GeoPackage abgerufen. Die Analysedatenbank liegt nur unter `work/`.
- **GRM2023:** Gerenderte WMS-PNGs (0,5 m/Pixel) mit Metadaten und Prüfsummen
  in `raw/grm2023/png/`; daraus erzeugte Baumschichtpolygone liegen
  ausschließlich in `work/`. PNGs sind keine amtlichen Baumkronen-Rohpolygone.
- **Wiener Bezirksgrenzen:** amtliches WFS, daraus die Wien-AOI.
- **Berechnung:** metrisch in EPSG:31256, Ausgabegeometrien in EPSG:4326.

## Berechnung

1. SIS-TYPE-Flächen bilden den Straßenraum. Geometrische Defekte werden nur
   mit nachvollziehbarer Flächenerhaltungsprüfung repariert. Fehlende
   Klassifikationen werden nicht stillschweigend als begrünt behandelt.
2. GIP2-EDGE-Achsen dienen zur Voronoi-basierten räumlichen Aufteilung.
   Die metrische Zuweisung wird mit einem festen Wien-Raster und
   Flächenbilanzprüfungen kontrolliert. Die GIP-Originaldatei bleibt unverändert.
3. Bodenbegrünung: Nur die BELAG-Codes **BL, ST, WI** gelten als begrünt;
   abweichende bzw. überlappende nicht begrünte Beläge werden konservativ
   behandelt. Für die einzelnen GIP-Abschnitte wird der Flächenanteil berechnet.
4. Baumkronenüberschirmung: GRM2023-WMS-Klassen werden aus den geprüften
   PNGs geometrisch abgeleitet und mit denselben Abschnittsflächen verschnitten.
   Boden- und Kronenanteile dürfen nicht addiert werden.
5. Die QA kontrolliert Flächenbilanz, Geometriegültigkeit, Quellprüfsummen,
   GIP-Zuordnung und Vollständigkeit des Wiener Gebiets.
6. **Veröffentlichung:** PMTiles enthalten nur FOW **2, 3, 14** und Abschnitte
   ab **100 m²**. Die Berechnungs- und QA-Grunddaten umfassen weiterhin
   die für die Flächenbilanz notwendigen GIP-Kanten; der FOW-Filter ist ein
   Veröffentlichungsfilter.

Die 20-m-Kandidatenanalyse erfasst außerdem nahe Fuß-/Radwege mit FOW
**15, 504, 505**, wenn eine geeignete Straßenachse am Paar beteiligt ist.
Sie **vereinigt** bislang weder Kanten noch Abschnittsflächen.

Die Werte **40 % Bodenbegrünung** und **60 % Baumkronenüberschirmung**
sind kartografische Referenzwerte, keine fachlich validierten Grenzwerte.
