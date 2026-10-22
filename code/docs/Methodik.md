# Methodik – vor dem SIS-Verschnitt

Die aktuelle Stufe berechnet CGAL-Segment-Voronoi aus originalen
LINEAR_USE-Linien (`base_type=1`) in EPSG:31256.

Die ursprüngliche `edge_id` wird bei der Segmentierung/Noding
bewahrt. CGAL liefert nun sowohl die Voronoi-Grenzen als auch die
tatsächlichen Sites. Nur Segment-Sites werden anhand des ursprünglichen
Eingabesegments zugeordnet. Die Schnittlänge der Site in einer
polygonisierten Zelle dient zur topologischen Verbindung. Mehrere
Segment-Sites derselben `edge_id` dürfen eine gemeinsame Fläche bilden.

**Punkt-Sites werden absichtlich nicht zugeordnet oder verteilt.**
Die erhaltenen unbelegten Flächen sind daher keine Fehler, die
automatisch mit einer benachbarten `edge_id` aufgefüllt werden.
Nicht eindeutig zuordenbare Segment-Sites hingegen führen zum
Abbruch statt zu einer heuristischen Korrektur.

Nach der Zellzuordnung erfolgt die Vereinigung nach `edge_id`
und räumlichem Zusammenhang, anschließend ein GeoJSON-Export.
**SIS kommt in diesem Schritt nicht vor.**

## Schnittprüfung und Reproduzierbarkeit

Nur positive Linienanteile innerhalb der Polygoninnenfläche
(`LineString.relate_pattern(Polygon, "1********")`) zählen als
Site-Zuordnung. Getrennt dokumentiert werden Randüberlagerungen,
Mehrfachtreffer verschiedener Polygoninnenflächen und Sites ohne
Innenflächentreffer. Punktzellen werden weiterhin **nicht** zugewiesen.

Weil die Wiener CGAL-Polygonisierung teuer ist, werden nach der
Polygonisierung alle Voronoi-Polygone sowie die auf originale
`edge_id` zurückgeführten Segment-Sites in einer SQLite-Datei
zwischengespeichert. Der Cache prüft die Prüfsummen der Originaldaten,
der AOI, des CGAL-Binarys und der Geometrieaufbereitung. Er dient
nur zur Wiederholung der Zuordnung ohne neue CGAL-Polygonisierung.

Bei nicht eindeutigen Site-Zuordnungen erzeugen wir zusätzlich eine
GeoJSON-Diagnose mit Segment-Sites und beteiligten Polygonflächen.
Keine automatische Zuordnung aus bloßen Grenzkontakten.
