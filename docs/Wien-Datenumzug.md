# Wien neu berechnen – saubere Verzeichnisstruktur

Seit dem 19. Oktober 2026 ist das alte `data/` lokal absichtlich
geleert worden. Es gibt **keine Datenmigration und keinen Pilotstand**
mehr. Der vollständige Wien-Lauf beginnt neu.

## Eingaben

Zwei bereits vorhandene GeoPackages liegen unter
`/mnt/c/Users/peter/Downloads/`:

- `gip_network_ogd.gpkg` – wird von der aktuellen SIS-V2-Pipeline
  als SQLite-GeoPackage **ausschließlich lesend** (`mode=ro&immutable=1`)
  verwendet. Es werden weder Sicherungskopien noch SQLite-WAL- oder
  SHM-Dateien im Downloads-Verzeichnis erzeugt.
- `FMZK_WIEN_GP.gpkg` – wird für SIS-V2 **nicht benötigt**, bleibt
  vollständig unangetastet.

**Niemals Downloads als Zielverzeichnis verwenden.**
Die Pfade werden beim Start auf Lesbarkeit geprüft. Die in der Pipeline
neu angeforderten WFS-/WMS-Kacheln und die AOI-Grenze werden direkt
innerhalb des Repositories abgelegt.

## Drei Datenbereiche (neben dem bisherigen Quellcode)

```text
ks-Gartenstrassen/
  scripts/                       # aktuelle Python- und Shell-Programme
  tests/
  docs/
  raw/                           # dauerhaft gesicherte Downloads
    aoi/wien.geojson
    aoi/bezirksgrenzen_wfs.geojson
    sis/wfs-kacheln/              # komprimierte SIS-WFS-Originalantworten
    grm2023/png/                  # GRM-GetMap-PNG und JSON-Metadaten
  work/                          # nur während des laufenden Jobs
    sis-wien.sqlite
    wien/gip.sqlite
    wien/raster.json
    wien/strassenraum/
    wien/grm2023/masken/
    ...
  output/                        # einzige aktuelle Endausgabe
    gip_abschnitte.geojson
    gip_abschnitte.csv
    bericht.json
    gartenstrassen.pmtiles
```

Die beiden großen GeoPackages werden **nicht** ins Repository kopiert.
`data/processed/`, `data/wien/` und frühere V0-/Pilotordner werden
nicht neu angelegt. Die historischen Skripte sind im normalen Wiener
Lauf nicht beteiligt.

## Neuen Wien-Lauf starten

Im Root des Git-Repositories (in WSL):

```bash
git status --short
git pull --ff-only
bash scripts/run-sis-v2-wien.sh
```

Die SIS-WFS-Antworten und GRM-PNGs müssen nach dem Löschen der bisherigen
Daten einmal neu geladen werden. Sobald sie unter `raw/` vorliegen,
werden sie bei einem abgebrochenen Lauf wiederverwendet.
GIP2 wird nur gelesen. Die bisherige FMZK-V0-Methode wird nicht
durchlaufen.

Der Stadtlauf verwendet ein 1.000-m-Analyseraster statt der alten
250-m-Pilotkachel und die vorhandene, unveränderte wissenschaftliche
SIS-V2-/GIP2-/GRM-Berechnungslogik.

**Nach vollständigem Erfolg**: Zuerst müssen alle vier Ergebnisdateien
vorliegen und der Abschlussbericht, die CSV-Zeilenanzahl und das
zugehörige Rastermanifest müssen zueinander passen. Danach entfernt
der Treiber automatisch **nur `work/`**. Rohdaten und Ergebnisse bleiben.
Bei einem Fehler wird `work/` nicht gelöscht.

## Bei Bedarf Arbeitsdaten behalten

Um nach dem Lauf die 20-m-GIP-Parallelkantenanalyse auszuführen:

```bash
SIS_WIEN_KEEP_WORK=1 bash scripts/run-sis-v2-wien.sh
bash scripts/run-gip-parallel-wien.sh
```

Danach kann die Ergebnisprüfung und Bereinigung separat erfolgen:

```bash
.venv/bin/python -m scripts.clean_wien_work
.venv/bin/python -m scripts.clean_wien_work --apply
```

Die erste Anweisung ist eine **schreibgeschützte Vorschau**.
Die zweite löscht ausschließlich `work/`, wenn die notwendigen
Ausgaben nachweislich korrekt vorhanden sind.

Wenn nur das PMTiles aus einem bereits vorhandenen
`output/gip_abschnitte.geojson` neu gebaut werden soll:

```bash
bash scripts/run-sis-v2-wien.sh --from pmtiles --until pmtiles
```

Dabei werden weder GeoPackages geöffnet noch WFS-/GRM-Downloads
durchgeführt. Die vollständige Stadtberechnung kann erheblich
aufwendiger sein; vorher ausreichend freien Speicherplatz prüfen.

## Lokal noch gestagte Codeänderungen

Die neun lokal gestagten Optimierungen vom 18. Oktober wurden
bereits unverändert (Git-Blob-Prüfsummen kontrolliert) mit PR #7
auf `main` übernommen. Der Patch
`~/gartenstrassen-arbeitsstand.patch` bleibt als externe Sicherung
bestehen. Falls `git pull --ff-only` wegen lokaler Änderungen
scheitert, zuerst den Git-Status ansehen und **kein**
`git reset --hard` verwenden.
