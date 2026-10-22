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
