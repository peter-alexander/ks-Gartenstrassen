# Wien-Komplettlauf: originale LINEAR_USE-Geometrien und SIS

```bash
GIP_NETWORK_SOURCE=/pfad/gip_network_ogd.gpkg bash code/scripts/run-gartenstrassen-wien.sh
```

Pipeline: nur LINEAR_USE (`base_type = 1`) aus der Quelldatei laden;
Original-Linien pro `object_id` unverändert in EPSG:31256 speichern;
Linien für CGAL segmentieren/noden; Voronoi-Polygone und ihre ursprüngliche
`edge_id` bestimmen; danach SIS-Straßenraum schneiden und geometrisch
berührende Teilflächen mit derselben `edge_id` vereinigen. Nicht
zusammenhängende Flächen erhalten eigenständige GeoJSON-Features.

Ausgaben:

- `cache/wien/linear_use_original.sqlite`
- `output/linear_use_original.geojson`
- `output/cgal_original_linear_use_sis_wien.geojson`
- `output/cgal_original_cell_ownership_audit.json`
- `output/cgal_original_linear_use_sis_wien.pmtiles`

Ein nicht bestandener oder veralteter QA-Bericht blockiert die
PMTiles-Erstellung, außer bei ausdrücklich gesetztem
`ALLOW_FAILED_QA=1` (ungeprüfte Sichtprüfung).
