# CGAL Segment-Voronoi – originale LINEAR_USE-Linien

Installation:

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake libcgal-dev libgmp-dev libmpfr-dev
```

Wiener Berechnung:

```bash
GIP_NETWORK_SOURCE=/pfad/gip_network_ogd.gpkg bash code/scripts/run-gartenstrassen-wien.sh
```

CGAL-Konstruktion: ursprüngliche LINEAR_USE-Linien, nur Segmentnoding und
Millimeterraster. Die Zellzuordnung erfolgt *nach der Polygonisierung*
mit direktem räumlichem LineString-Polygon-Schnitt, bevor SIS geschnitten
wird. Bei 0 oder mehr als 1 Treffern wird die Linie diagnostiziert und
nicht zugeordnet; bei unterschiedlichen edge_ids für dieselbe Fläche
wird die Fläche separat ausgegeben.

Unter `output/cgal_original_line_intersections_sis_wien__*` liegen vier GeoJSON-Diagnoselayer und ein
JSON-Bericht. Erst bei eindeutiger Zuordnung erfolgt der SIS-Verschnitt.
Dann entstehen `output/cgal_original_line_intersections_sis_wien.geojson` und optional PMTiles.

Wichtig: Auch reine Punktberührungen zählen im Schnitt. Die
Linien/Polygon-Schnittzuordnung wird auf echten Wiener Daten noch validiert.
