# Gartenstraßen Wien

GIS-Vorbereitung und experimentelle Segment-Voronoi-Aufteilung des Wiener
Straßenraums aus **originalen GIP-LINEAR_USE-Geometrien** und SIS.

## Daten

- Quelle: `LINEAR_USE` aus `gip_network_ogd.gpkg`, ausschließlich `base_type = 1`
- Jede ursprüngliche Linie (`object_id`) bleibt erhalten; ihre `edge_id` bleibt unverändert
- Berechnung metrisch in EPSG:31256
- CGAL: Original-Linien werden nur in gerade Teilsegmente zerlegt, millimetergenau
  gerundet und an echten Schnittpunkten genodet
- **Keine künstlichen Mittelachsen, kein Zusammenmitteln benachbarter Linien**
- Voronoi-Polygone bekommen vor dem SIS-Verschnitt eine ursprüngliche `edge_id`
- Nach dem Verschnitt werden nur räumlich berührende Polygone derselben
  `edge_id` zusammengefasst. Getrennte Flächengruppen bleiben eigene Features.

Die rekonstruierte Voronoi-Polygonisierung und insbesondere die Approximation
parabolischer Grenzen sind vor fachlicher Freigabe mit realen Daten zu prüfen.

## Wien berechnen

Voraussetzungen: Python-Venv mit `code/requirements-analysis.txt`, CMake und
CGAL sowie für den PMTiles-Export `tippecanoe`.

```bash
GIP_NETWORK_SOURCE=/pfad/gip_network_ogd.gpkg bash code/scripts/run-gartenstrassen-wien.sh
```

Der SIS-/GRM-Cache wird bei Bedarf separat vorbereitet. Alte
Mittelachsen-Caches und alte CGAL-Ausgaben werden **nicht** wiederverwendet.

Ausgaben:

- `cache/wien/linear_use_original.sqlite`: originale LINEAR_USE-Linien
- `output/linear_use_original.geojson`: Original-Linien für die Sichtprüfung
- `output/cgal_original_linear_use_sis_wien.geojson`: SIS-Voronoi-Teilflächen
- `output/cgal_original_cell_ownership_audit.json`: unabhängige Stichprobenprüfung
- `output/cgal_original_linear_use_sis_wien.pmtiles`: Kartenansicht (nur bei bestandener QA)

Die Ausgabedateien werden nicht stillschweigend überschrieben. Ein nicht
bestandener QA-Lauf stoppt den PMTiles-Export; `ALLOW_FAILED_QA=1` erlaubt
ausschließlich eine ausdrücklich ungeprüfte Vorschau.
