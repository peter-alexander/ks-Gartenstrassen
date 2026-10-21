# CGAL Segment-Voronoi – originale LINEAR_USE-Geometrien

Installation (WSL/Ubuntu):

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake libcgal-dev libgmp-dev libmpfr-dev
```

Vollständige Pipeline:

```bash
GIP_NETWORK_SOURCE=/pfad/gip_network_ogd.gpkg bash code/scripts/run-gartenstrassen-wien.sh
```

Nur CGAL/SIS-GeoJSON:

```bash
bash code/scripts/run-cgal-voronoi-debug-wien.sh
```

Vorher müssen die SIS-Daten und der originale LINEAR_USE-Cache vorhanden sein.
Ergebnis: `output/cgal_original_linear_use_sis_wien.geojson`.

Der C++-Exporter liest noded Original-Segmente in ganzzahligen
Millimetern von stdin. `--edges` liefert die Segment-, Strahl- und
Geradenstücke der Dualgrenzen; `--bounds` begrenzt den Zielbereich.
Die GIS-Verarbeitung weist den polygonisierten Flächen `edge_id` aus
den Originalsegmenten zu, schneidet SIS und fasst anschließend je
`edge_id` nur räumlich berührende Flächen zusammen.

Die Linearisierung parabolischer CGAL-Grenzen ist eine Approximation.
GeoJSON dient bis zur Validierung als experimenteller Debug-Export.
