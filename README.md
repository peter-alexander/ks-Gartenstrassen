# Gartenstraßen Wien

GIS-Vorbereitung für die Wiener Gartenstraßenanalyse.

Der aktuelle Zwischenstand enthält bewusst **keine GIP-Straßenkanten,
keine Voronoi-Abschnittszuordnung und keine Kreuzungsausschnitte**.
Die nächste Abschnittsmethode wird darauf neu aufgebaut.

## Verzeichnisstruktur

```text
ks-Gartenstrassen/
  code/                 # Python-Skripte, Tests und Methodik
  raw/                  # unveränderte WFS-/WMS-Downloads, dauerhaft
  cache/                # quell- und methodengebundene Aufbereitung, dauerhaft
    sis-wien.sqlite
    wien/
      aoi.geojson
      raster.json
      strassenraum/
      masken/
  work/                 # künftig ausschließlich laufabhängige, löschbare Daten
  output/               # künftig ausschließlich Ergebnisse der neuen Methode
```

## Vorbereitung ausführen

```bash
bash code/scripts/run-sis-v2-wien.sh
```

Der Ablauf erzeugt bzw. validiert ausschließlich:

1. Wiener SIS-WFS-Rohcache unter `raw/sis/wfs-kacheln/`
2. `cache/sis-wien.sqlite`
3. Wien-AOI und Raster unter `cache/wien/`
4. SIS-Straßenraumkacheln unter `cache/wien/strassenraum/`
5. GRM2023-Rohbilder unter `raw/grm2023/`
6. GRM-Kronenmasken unter `cache/wien/masken/`

Diese Daten bleiben erhalten, solange Quelle und jeweilige
Aufbereitungsmethode unverändert sind.

## LINEAR_USE-Mittelachsen – neuer Abschnittsbaustein

Der neue Ansatz liest ausschließlich `LINEAR_USE` aus
`gip_network_ogd.gpkg`, filtert auf `base_type = 1` und gruppiert
**nur nach `edge_id`**.

- genau eine LINEAR_USE-Linie je `edge_id`: unverändert übernehmen
- mehrere LINEAR_USE-Linien je `edge_id`: deterministische geometrische
  Mittelachse aus gleichmäßig entlang der normierten Bogenlänge
  abgetasteten Punkten
- keine Verwendung von MAX_SPEED
- keine Namen-, Breiten-, Distanz- oder Winkelheuristik
- keine Kreuzungs-/Voronoi-Logik

Stand-alone für Wien:

```bash
bash code/scripts/run-linear-use-wien.sh
```

Ausgaben:

```text
cache/wien/linear_use.sqlite
output/linear_use_mittelachsen.geojson
```

Der SQLite-Cache enthält zusätzlich jede ursprüngliche LINEAR_USE-Zeile
mit `object_id`, `edge_id`, `edge_percentage_from/to`, `length_m`,
`feature_name` und Originalgeometrie in EPSG:31256. Das GeoJSON dient
nur der visuellen Kontrolle der erzeugten Mittelachsen.


## Bewusst entfernt

Die frühere Verarbeitung der Layer EDGE/NODE/TURN_USE aus
`gip_network_ogd.gpkg` ist vollständig aus der aktiven Analyse entfernt.
Damit entfallen auch die darauf beruhenden Voronoi-Flächen,
Parallelkantenlogik, FOW-Publikationsfilter, Querschnitts-/Kreuzungsschnitte,
GIP-basierte QA, Messung und PMTiles-Erzeugung.

Die neue Methode wird schrittweise auf den dauerhaft vorbereiteten
SIS- und GRM-Daten aufgebaut.

## CGAL-Segment-Voronoi: Flächen-Debug

Das aktuelle Segment-Voronoi-Verfahren verwendet **ausschließlich CGAL**.
Die alten Boost-/pyvoronoi-Diagnosen, Benchmarks und punktbasierten
Voronoi-Debugverfahren sind entfernt. Die Millimeter-Noding-Vorbereitung
bleibt erhalten.

Der experimentelle Flächendebug konstruiert CGAL aus allen Wiener
LINEAR_USE-Segmenten, rekonstruiert die Voronoi-Grenzen im gewählten
Fenster, polygonisiert sie und verschneidet sie mit der verifizierten
SIS-Straßenmaske.

```bash
bash code/scripts/run-cgal-voronoi-debug-wien.sh
```

Es wird immer **ganz Wien** gerechnet und mit der SIS-Maske verschnitten.
Ausgabe:
`output/cgal_segment_voronoi_sis_debug.geojson` (EPSG:4326).

**Debug, noch keine Fachfreigabe:** Kurvenlinearisierung und Zellzuordnung
sind auf realen Daten geometrisch zu verifizieren. Kein Boost-Fallback.
Details und Installation: [code/cgal/README.md](code/cgal/README.md).
