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

## Bewusst entfernt

Die frühere Verarbeitung der Layer EDGE/NODE/TURN_USE aus
`gip_network_ogd.gpkg` ist vollständig aus der aktiven Analyse entfernt.
Damit entfallen auch die darauf beruhenden Voronoi-Flächen,
Parallelkantenlogik, FOW-Publikationsfilter, Querschnitts-/Kreuzungsschnitte,
GIP-basierte QA, Messung und PMTiles-Erzeugung.

Die neue Methode wird schrittweise auf den dauerhaft vorbereiteten
SIS- und GRM-Daten aufgebaut.
