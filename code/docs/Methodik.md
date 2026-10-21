# Methodik – Wiener Gartenstraßen

## Quellen

- Wiener SIS-Straßenraumflächen
- GRM2023-Vegetation
- GIP `LINEAR_USE`, ausschließlich `base_type=1`
- EPSG:31256 als metrisches Berechnungssystem

## Voronoi und Straßenzuordnung

1. Original-Linien (`object_id`, `edge_id`) ohne Mitteln einlesen.
2. Für CGAL segmentieren und an echten Kreuzungen noden.
3. Wienweit Voronoi-Grenzen berechnen und polygonisieren.
4. Original-Linien direkt mit den vollständigen Voronoi-Flächen schneiden.
   Nur eine Linie mit **genau einem** Polygon-Treffer darf ihre `edge_id`
   diesem Polygon vorschlagen.
5. Nulltreffer, Mehrfachtreffer, widersprüchliche `edge_id` einer Fläche
   und alle unzugeordneten Flächen als eigene Diagnoselayer ausgeben.
6. Bei uneindeutiger Zuordnung vor SIS stoppen, andernfalls mit dem
   SIS-Straßenraum verschneiden.
7. Nur berührende Flächen derselben `edge_id` vereinigen;
   getrennte Teilflächen bleiben eigene Features.
8. Gültigkeit und Flächenbilanz prüfen.

Das strikte `intersects` berücksichtigt auch eine bloße
Randberührung. Diese Fälle werden nicht automatisch korrigiert.
Die Rekonstruktion und Parabelapproximation der CGAL-Grenzen
bleibt bis zur Prüfung auf echten Daten experimentell.
