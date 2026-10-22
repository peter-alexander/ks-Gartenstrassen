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


## Direkte native CGAL-Face-Topologie statt räumlicher Zuordnung

Aktuell wird `CGAL::Voronoi_diagram_2` mit dem Segment-Delaunay-Graphen
verwendet. Eine Voronoi-Face verweist selbst auf die originale
Generator-Site. Bei Segment-Sites wird die `edge_id` über das während
des Nodens unverändert gespeicherte unterstützende Eingabesegment
zurückgewonnen. CGAL liefert die Halbkanten der zusammengehörigen
Voronoi-Face; die kurvigen Randkanten werden beim Export geometrisch
linearisiert und als geschlossene Fläche rekonstruiert.

Die alte Nachprüfung „Schneidet die CGAL-Site ein oder mehrere
polygonisierte Flächen?“ ist **keine** Quelle der Zugehörigkeit mehr.
Die davor gemeldeten vermeintlichen `edge_id`-Konflikte erklären
nicht die ursprüngliche Generatoridentität und werden im nativen
Verfahren nicht verwendet.

Ausdrücklich ausgeschlossen sind Punkt-Sites und deren Voronoi-Faces.
Danach werden nur Flächen derselben `edge_id` vereinigt, getrennte
Komponenten bleiben getrennt. Das Zwischenergebnis entsteht vor SIS.
