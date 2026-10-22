# Gartenstraßen Wien

Aktuelle Forschungsstufe: Voronoi aus **originalen LINEAR_USE-Linien**
(`base_type=1`) mit CGAL. Anders als bisher bleibt die Identität der
Generatorsegmente im CGAL-Site-Export erhalten und wird auf die
ursprüngliche `edge_id` zurückgeführt.

## Ablauf bis vor SIS

1. LINEAR_USE-Geometrien (EPSG:31256) ohne Mittelachsen laden.
2. Originalsegmente für CGAL millimetergenau segmentieren/noden.
3. CGAL: Dualgrenzen **und tatsächliche Sites** gemeinsam ausgeben.
4. Für jede **Segment-Site** die `edge_id` ihres ursprünglichen
   Eingabesegments bestimmen; polygonisierte Zelle anhand der positiven
   Schnittlänge mit der tatsächlichen Site verbinden. Keine
   künstlichen Prüfpunkte, keine Nearest-Heuristik.
5. Zugeordnete Zellen derselben `edge_id` vereinigen; nur räumlich
   zusammenhängende Teile zu einem Feature zusammenfassen.
6. Ergebnis als GeoJSON **vor SIS** exportieren.

**Punktzellen werden nicht behandelt oder einer `edge_id` zugewiesen.**
Im Zwischenergebnis verbleiben daher bewusst unbelegte Flächen.
Ungültige oder widersprüchliche Segment-Site-Zuordnungen stoppen den
Export. Das ist ein experimenteller Geometrieexport, keine vollständige
Flächenpartition und noch kein SIS- oder PMTiles-Produkt.

```bash
git pull --ff-only
bash code/scripts/run-gartenstrassen-wien.sh
```

Ausgabe: `output/cgal_original_segment_sites_pre_sis_wien.geojson`.
Der bislang fehlerhafte vollständige LINEAR_USE-Linien/Polygon-
Schnittansatz ist nicht mehr Bestandteil des aktiven Wiener Laufs.
Vorhandene Eingabecaches werden wiederverwendet, alte GeoJSON-Ergebnisse
nicht überschrieben.

Der SIS-Verschnitt wird erst nach Prüfung des Vor-SIS-Ergebnisses
wieder aufgenommen.

## Segment-Site-Prüfung und fortsetzbarer Lauf

Die Zuordnung einer CGAL-Segment-Site zu einer polygonisierten Zelle
verwendet die **positive Schnittdimension mit dem Polygoninneren**
(DE-9IM), nicht die bloße Länge von `intersection()`: entlang
von Polygonkanten liegende Segmentanteile zählen nicht als Eigentum.
Echte Treffer in mehreren Polygoninnenflächen werden weiterhin
abgelehnt. Punktzellen bleiben unzugeordnet.

Nach der teuren Polygonisierung wird vor der Zuordnung ein geprüfter
SQLite-Zwischenspeicher erzeugt:
`output/cgal_original_segment_sites_pre_sis_wien__geometry_checkpoint.sqlite`.
Er wird nur wiederverwendet, wenn Eingangsdaten, AOI, CGAL-Binary und
Geometrieerzeugungscode identisch sind. Nach einem Fehler können so
nur die Zuordnung und der Dissolve erneut ausgeführt werden.

Ein Zuordnungsbericht und eine kleine, kartierbare Problemgeometrie
werden auch bei einem Fehler gespeichert:

- `output/cgal_original_segment_sites_pre_sis_wien__site_zuordnung.json`
- `output/cgal_original_segment_sites_pre_sis_wien__site_konflikte.geojson`

Ältere Berichte werden archiviert, nicht überschrieben.
