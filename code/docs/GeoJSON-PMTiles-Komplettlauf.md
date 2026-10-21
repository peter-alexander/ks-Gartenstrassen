# Originale LINEAR_USE-Linien → CGAL-Voronoi → SIS

```bash
GIP_NETWORK_SOURCE=/pfad/gip_network_ogd.gpkg bash code/scripts/run-gartenstrassen-wien.sh
```

Die räumliche Zuordnung basiert jetzt ausschließlich auf
Original-`LINEAR_USE`-Linien, nicht auf künstlichen Stichproben.
Jede Linie muss genau eine polygonisierte Voronoi-Fläche schneiden;
Mehrfach- und Nulltreffer werden in separaten GeoJSON-Dateien gespeichert.
Widersprüchliche `edge_id`-Vorschläge an einer Fläche und nicht
eindeutig zugeordnete Flächen haben ebenfalls eigene GeoJSON-Dateien.

Eindeutige Zuordnungen werden erst danach mit SIS geschnitten.
Berührende Flächen derselben `edge_id` werden vereinigt;
räumlich getrennte Flächen bleiben getrennt.

Ergebnisse und Bericht stehen unter `output/cgal_original_line_intersections_sis_wien*`.
Die Python-Skripte überschreiben bereits vorhandene Ausgaben nicht.
Nicht bestandene Zuordnung blockiert die Veröffentlichung.
