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
