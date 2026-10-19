# Wiener Vorbereitungslauf

Vom Repository-Root:

```bash
git pull --ff-only
bash code/scripts/run-sis-v2-wien.sh
```

## Dauerhafte Daten

- `raw/aoi/`: Wiener AOI-Quelle
- `raw/sis/wfs-kacheln/`: SIS-WFS-Rohantworten
- `raw/grm2023/`: GRM2023-PNGs und Metadaten
- `cache/sis-wien.sqlite`: vollständiger SIS-Index
- `cache/wien/aoi.geojson`: verwendete Wien-AOI
- `cache/wien/raster.json`: 1-km-Raster mit 75-m-Halo
- `cache/wien/strassenraum/`: vorbereitete SIS-Straßenraumkacheln
- `cache/wien/masken/`: vorbereitete GRM-Kronenmasken

## Phasen

```text
aoi
grid
street
grm-fetch
grm-build
```

Es gibt bewusst keine GIP-, Voronoi-, Partitionierungs-, Trim-, QA-,
Mess- oder PMTiles-Phase mehr. Ebenso werden keine Kreuzungen oder
Knotenbereiche ausgeschnitten.

`work/` wird durch diesen Vorbereitungslauf derzeit nicht benötigt.
Die neue Abschnittsmethode kann später ihre ausschließlich laufabhängigen
Zwischendaten dort ablegen.
