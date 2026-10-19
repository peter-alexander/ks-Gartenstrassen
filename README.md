# Gartenstraßen Wien

Analyse der Bodenbegrünung und Baumkronenüberschirmung des Wiener Straßenraums anhand von
SIS-Belagsflächen, dem GIP2-Straßennetz und dem Grünraummonitoring 2023.

## Einzige Verzeichnisstruktur

```text
ks-Gartenstrassen/
  code/                 # Python-Skripte, Tests, Methodik, Abhängigkeiten
    scripts/
    tests/
    docs/
    requirements-analysis.txt
  raw/                  # heruntergeladene WFS-/WMS-Originaldaten, dauerhaft
  cache/                # aufbereitete GIS-Daten, dauerhaft
    sis-wien.sqlite
    wien/
      aoi.geojson
      raster.json
      gip.sqlite
      gip_merged.sqlite
      strassenraum/
      masken/
      aufteilung_roh.sqlite
      aufteilung.sqlite
      qa.gpkg
  work/                 # ausschließlich temporäre Messung und Zwischenausgabe
  output/               # aktuelle CSV, GeoJSON, PMTiles und Bericht
```

**Die beiden GeoPackages** unter `/mnt/c/Users/peter/Downloads/` werden **niemals beschrieben**.
Für den Wiener SIS-Lauf wird nur `gip_network_ogd.gpkg` im unveränderlichen
SQLite-Lesemodus verwendet. `FMZK_WIEN_GP.gpkg` bleibt unberührt.

## Ausführen

Die Python-Umgebung liegt wie bisher in `.venv/` am Repository-Root.

```bash
bash code/scripts/run-sis-v2-wien.sh
```

Die Quellen-Downloads verbleiben in `raw/`, temporäre Daten in `work/` und
die aktuellen Enddateien in `output/`. Dort liegen insbesondere
**`gip_abschnitte.geojson` und `gartenstrassen.pmtiles`** sowie CSV,
Bericht und `freigabe.json` als gemeinsamer Prüfsummennachweis.

SIS-Index, GIP-Indizes, Straßenraumkacheln, GRM-Masken, Raster,
Voronoi-Partitionen und QA-GeoPackage liegen **dauerhaft unter `cache/`**.
Nur `work/wien/messung.sqlite` und `work/wien/ergebnisse/` sind temporär.
Die Cachedateien werden anhand von Quellen, Raster und Methode geprüft;
unpassende ältere Partitionen werden nicht überschrieben.

Nach erfolgreichem vollständigem Lauf, gemeinsamer Veröffentlichung
und Ergebnisprüfung wird **ausschließlich `work/`** entfernt.
`cache/`, `raw/` und `output/` bleiben erhalten.

Für zusätzliche Auswertungen des laufenden Mess-Checkpoints kann `work/` beibehalten werden:

```bash
SIS_WIEN_KEEP_WORK=1 bash code/scripts/run-sis-v2-wien.sh
bash code/scripts/run-gip-parallel-wien.sh
```

Parallele Kanten werden im Schritt `gip-merge` **vor der Voronoi-Zuordnung
konservativ zu Straßenraumgruppen zusammengefasst**. Original-GIP-IDs,
Quelllinien und sämtliche 5-m-Stützpunktkoordinaten bleiben nachvollziehbar.
Die Gruppenzuordnung steht dauerhaft in
`output/gip_kanten_zuordnung.csv` und `original_gip_ids` im GeoJSON.
Mehrdeutige Rad-/Fußweganbindungen bleiben unabhängig; die einzelnen
Gruppen sind anhand direkter Parallel-Evidenz abgesichert. Die Veröffentlichung
enthält FOW 2/3/14 ab 100 m²; Fuß-/Radwege 15/504/505 dienen nur als
begleitende Infrastruktur beim Parallelabgleich.

**Dokumentation:** [Wien-Lauf](code/docs/Wien-Lauf.md),
[Methodik](code/docs/Methodik.md),
[FOW-Auswahl](code/docs/GIP-FOW-Auswahl.md),
[20-m-Parallelkanten](code/docs/Diagnose-Parallele-GIP-Achsen.md).

Die historischen V0-/Pilotskripte und Versuchsberichte sind nicht Teil des aktuellen
Projekts; die alte Historie ist weiterhin in Git nachvollziehbar.
