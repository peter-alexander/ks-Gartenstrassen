# Wiener Datenbereinigung: ein Rohdatenbestand, ein Arbeitsbereich, eine Ausgabe

## Zielstruktur

```text
ks-Gartenstrassen/
  scripts/            # aktueller Python-Code, derzeit noch am Repo-Root
  tests/              # automatisierte Tests
  docs/               # Dokumentation
  raw/                # dauerhafte Originaldownloads: GIP2, FMZK, SIS-WFS, GRM-PNG
    gip_network_ogd.gpkg
    FMZK_WIEN_GP.gpkg
    aoi/wien.geojson
    sis/wfs-kacheln/
    grm2023/png/
  work/               # ausschließlich berechnete, erneut erzeugbare Arbeitsdaten
    sis-wien.sqlite
    wien/gip.sqlite
    wien/raster.json
    wien/grm2023/masken/
  output/             # einzig gültige aktuelle Wiener Ausgabe
    gip_abschnitte.csv
    gip_abschnitte.geojson
    bericht.json
    gartenstrassen.pmtiles
```

Die historische Struktur `data/` wird nach einer getrennten Validierungsphase
entfernt. Ein Umbau von `scripts/`, `tests/` und `docs/` in einen
gemeinsamen `code/`-Unterordner ist **noch nicht Teil dieser Phase**; vor
einer Verlagerung müssen Importpfade, CI und Paketstruktur umgestellt werden.

## 0. Vorbedingungen

Kein laufender Wien-Prozess und **keine offenen SQLite-Verbindungen**.
Die neun lokalen Änderungen vom 18. Oktober wurden als PR #7 auf
`main` übernommen. Vor `git pull` die lokale Arbeitskopie auf Konflikte
mit dem bereits gesicherten Patch prüfen.

## 1. Nur Vorschau

```bash
.venv/bin/python -m scripts.consolidate_wien_data
```

Es wird **nichts verändert**. Alle erwarteten Pfade werden aufgeführt,
Kollisionen zwischen Quelle und Ziel führen zum Abbruch.

## 2. Tatsächlichen Umzug durchführen

```bash
.venv/bin/python -m scripts.consolidate_wien_data --apply
```

Verwendet lokale Umbenennungen, keine Kopien der 7,2-GB-GIP2-Datei.
Wiederholbar, da bereits verschobene Eingaben erkannt werden. Der Befehl
überprüft abschließend Wien-Raster und GIP-Index sowie die vier
aktuellen Ergebnisdateien. Kein automatisch ausgeführtes `rm -rf`.

Enthaltene Quellkacheln (einschließlich JSON-Metadaten) bleiben im
dauerhaften `raw/`-Verzeichnis. GRM-Masken, GIS-SQLites und
Voronoi-Fragmente verbleiben ausschließlich in `work/`.

## 3. Alte Arbeitsstände entfernen (separat)

Zuerst Vorschau:

```bash
.venv/bin/python -m scripts.consolidate_wien_data --prune-legacy
```

Nur nach Sichtung und vollständiger Ergebnisprüfung:

```bash
.venv/bin/python -m scripts.consolidate_wien_data --prune-legacy --apply
```

Das entfernt ausschließlich **`data/processed/`**, **`data/cache/`**
und **`data/wien/`**. `data/raw/` mit möglicherweise noch nicht
klassifizierten Quell-Dateien wird absichtlich nicht automatisch
gelöscht. Alle Zielpfade unter `raw/`, `output/` sowie die
verifizierte Ergebnisdatei müssen vorhanden sein; bei Fehlern
bricht die Bereinigung ab.

## 4. Wien-Lauf starten

```bash
bash scripts/run-sis-v2-wien.sh
```

Dauerhafte WFS- und WMS-Antworten landen nur in `raw/`;
neu berechnete Indizes und Masken liegen in `work/`. Die
fertigen CSV-/GeoJSON-/Bericht-/PMTiles-Ausgaben liegen in `output/`.

Nur PMTiles aus vorhandenem GeoJSON neu erzeugen:

```bash
bash scripts/run-sis-v2-wien.sh --from pmtiles --until pmtiles
```

Anders als früher wird dabei der Wiener SIS-Index nicht neu aufgebaut.
Die diagnostischen 20-m-GIP-Parallelpaare werden unter `work/wien/`
berechnet und nicht automatisch veröffentlicht.

## 5. Nach einem nachweislich erfolgreichen Gesamtlauf

```bash
.venv/bin/python -m scripts.consolidate_wien_data --clean-work
.venv/bin/python -m scripts.consolidate_wien_data --clean-work --apply
```

Die zweite Anweisung entfernt **nur `work/`**, nachdem die
aktuellen vier Ergebnisdateien einschließlich PMTiles-Header und
Abschlussbericht geprüft wurden. `raw/` und `output/` bleiben.

**Ein wesentlicher Vorbehalt:** Die derzeitige Migration kann lokal
nicht ausgeführt werden; der WSL-Datenträger steht GitHub Actions und
dieser Umgebung nicht zur Verfügung. Vor destruktiven Schritten müssen
die realen Dateien lokal überprüft werden.
