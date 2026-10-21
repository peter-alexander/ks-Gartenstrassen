# Gartenstraßen Wien

GIS-Vorbereitung und experimentelle CGAL-Segment-Voronoi-Aufteilung des
Wiener Straßenraums aus originalen GIP-LINEAR_USE-Geometrien und SIS.

## Methodik

1. Originale `LINEAR_USE`-LineStrings mit `base_type=1` einlesen;
   `object_id` und `edge_id` bleiben erhalten (keine Mittelachsen).
2. Originalgeometrie für CGAL in Teilsegmente zerlegen, auf ein
   Millimeterraster runden und an Kreuzungen noden.
3. Das vollständige Wiener Voronoi-Diagramm polygonisieren.
4. **Jede originale Eingabelinie** gegen einen räumlichen Index aller
   polygonisierten Flächen prüfen (`intersects`):
   - keine Fläche: eigener GeoJSON-Layer
   - mehrere Flächen: eigener GeoJSON-Layer
   - genau eine Fläche: `edge_id` dieser Fläche vorschlagen
   - widersprüchliche `edge_id` an einer Fläche: Konflikt-GeoJSON
   - jede noch nicht eindeutig zugewiesene Fläche: weiterer GeoJSON-Layer
5. Nur bei vollständig eindeutiger Zuordnung: mit SIS verschneiden,
   je `edge_id` nur zusammenhängende Flächen vereinigen,
   räumlich getrennte Gruppen als eigene GeoJSON-Features belassen.

Bei `intersects` zählt **auch die Berührung eines Polygonrandes an einem
einzigen Punkt** als Treffer. Solche Mehrfachtreffer werden absichtlich
sichtbar gemacht; es wird keine automatische Entfernungsheuristik eingesetzt.

## Wien ausführen

```bash
GIP_NETWORK_SOURCE=/pfad/gip_network_ogd.gpkg bash code/scripts/run-gartenstrassen-wien.sh
```

Vorhandene Wiener SIS-/GRM-Caches und `cache/wien/linear_use_original.sqlite`
werden weiterverwendet; die früheren Voronoi-Zuordnungen nicht.

Ausgabedateien:

- `output/linear_use_original.geojson`: originale LINEAR_USE-Linien
- `output/cgal_original_line_intersections_sis_wien__linien_mehrere_flaechen.geojson`
- `output/cgal_original_line_intersections_sis_wien__linien_ohne_flaeche.geojson`
- `output/cgal_original_line_intersections_sis_wien__flaechen_edge_id_konflikt.geojson`
- `output/cgal_original_line_intersections_sis_wien__flaechen_ohne_eindeutige_edge_id.geojson`
- `output/cgal_original_line_intersections_sis_wien__zuordnungsbericht.json`
- `output/cgal_original_line_intersections_sis_wien.geojson`: nur bei eindeutiger Zuordnung und SIS-QA
- `output/cgal_original_line_intersections_sis_wien.pmtiles`: nur bei erfolgreichem Gesamtlauf

Der gesamte Wien-Lauf wird bei einem ungeklärten Schnittfall vor dem
SIS-Export gestoppt. Die vier Diagnoselayer werden trotzdem gespeichert.
Unverändert gelten die geometrischen Validitäts- und Flächenbilanzprüfungen.
