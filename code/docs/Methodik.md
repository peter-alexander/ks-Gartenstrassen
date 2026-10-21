# Methodik – Wiener Gartenstraßen

## Quellen und Vorbereitung

- SIS (Stadt Wien): geprüfte Straßenraumflächen je Wiener Rasterkachel
- GRM2023: Vegetations-/Baumkronenmasken
- GIP `LINEAR_USE`: ausschließlich `base_type = 1` als originäre
  Liniengeometrien, mit unveränderter `object_id` und `edge_id`
- Alle Berechnungen metrisch in EPSG:31256

## Segment-Voronoi und Straßenraum

1. Original-Linien ohne Mittelachsenbildung einlesen.
2. Für CGAL in gerade Segmente zerlegen, auf 1 mm quantisieren, kreuzungsgenau noden.
3. Segment-Voronoi-Grenzen für Wien berechnen und polygonisieren.
4. Den Voronoi-Flächen vor dem Verschnitt die ursprüngliche `edge_id` zuweisen.
5. Flächen mit dem SIS-Straßenraum verschneiden.
6. Je `edge_id` nur berührende Flächen vereinen; getrennte Teilflächen
   als separate Features ausgeben.
7. Flächenbilanz, gültige Geometrien und räumliche Zuordnung prüfen.

Die genaue räumliche Korrektheit approximierter Voronoi-Grenzen ist im
experimentellen Wiener Lauf noch zu validieren. Es wird keine
GIP-EDGE-/NODE-/TURN_USE-Abschnittsbildung verwendet.
