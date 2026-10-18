# Wiener Gesamtlauf

Vom Repository-Root aus ausführen:

```bash
git status --short
git pull --ff-only
bash code/scripts/run-sis-v2-wien.sh
```

**Quelle unter Windows (nur lesen):**
`/mnt/c/Users/peter/Downloads/gip_network_ogd.gpkg`. Die Datei
`FMZK_WIEN_GP.gpkg` im selben Ordner wird für die aktuelle SIS-Pipeline
nicht benötigt. Keine Kopien, Sicherungsdateien, Datenbanken oder SQLite-Sidecars
in Downloads erzeugen.

**Daten im Repository:**

- `raw/aoi/`: amtliche Bezirksgrenzen und Wien-AOI
- `raw/sis/wfs-kacheln/`: heruntergeladene, komprimierte Originalantworten
- `raw/grm2023/png/`: GRM-PNGs und Herkunftsmetadaten
- `work/`: SIS-/GIP-Indizes, Straßenräume, Partitionen, Kronenmasken
- `output/`: **`gip_abschnitte.geojson` und `gartenstrassen.pmtiles`**,
  außerdem `gip_abschnitte.csv`, `bericht.json` und `freigabe.json`
  (SHA-256-Prüfsummen für den gemeinsam freigegebenen Ergebnisstand)

Die heruntergeladenen Dateien werden bei einem unterbrochenen Lauf aus
`raw/` wiederverwendet. Die Straßenraumkacheln werden bei identischen
Quellprüfsummen nicht erneut aus SIS vereinigt. In der Messphase hält
`work/wien/messung.sqlite` nach jeder Kachel **atomar die fertigen
Kennzahlen** fest. Ein Wiederanlauf übernimmt diese Werte, wenn der SIS-,
GIP-, Partitionierungs- und GRM-Stand identisch geblieben ist.

GeoJSON und CSV entstehen zuerst unter `work/wien/ergebnisse/`.
Erst nach erfolgreichem PMTiles-Neubau übernimmt die Veröffentlichung
die vier Dateien nach `output/` und schreibt **zuletzt**
`output/freigabe.json` mit ihren SHA-256-Prüfsummen. Ein
unterbrochener Export ist damit nicht als fertig freigegeben.

**Nur nach einem erfolgreichen vollständigen Lauf** und Prüfung des
Freigabemarkers, aller Ergebnisprüfsummen, des Wiener Rastermanifests,
der CSV-Abschnittszahl und der vorhandenen GRM-Werte wird
`work/` automatisch entfernt. Bei Fehlern bleiben die
Arbeitsdaten samt Kachelcheckpoints erhalten. Bei einem Lauf mit
`--no-grm` findet kein automatisches Löschen statt.

Vor einer 20-m-Diagnose den Index aufbewahren:

```bash
SIS_WIEN_KEEP_WORK=1 bash code/scripts/run-sis-v2-wien.sh
bash code/scripts/run-gip-parallel-wien.sh
```

Nur das PMTiles aus dem vorhandenen GeoJSON neu erzeugen:

```bash
bash code/scripts/run-sis-v2-wien.sh --from pmtiles --until pmtiles
```

Nur `work/` nach Prüfung entfernen:

```bash
PYTHONPATH=code .venv/bin/python -m scripts.clean_wien_work
PYTHONPATH=code .venv/bin/python -m scripts.clean_wien_work --apply
```

Das zweite Kommando löscht ausschließlich `work/`, niemals `raw/`,
`output/` oder die Windows-GeoPackages.

**Hinweis für lokale Git-Änderungen:** Die Optimierungen der neun lokal
gestagten Dateien wurden bereits mit PR #7 nach `main` übernommen.
Vor der Aktualisierung der Arbeitskopie diese ggf. mit
`git stash push -m "SIS-Optimierungen bereits auf main"` sichern.
Kein `git reset --hard`.

## Dauerhafte Mess- und Performancehinweise

Die Shell-Pipeline protokolliert pro Phase die benötigten Sekunden.
Die Berechnung bleibt absichtlich seriell, bis die realen Laufzeiten
im neuen Wiener Durchgang vorliegen. Die bisherige FOW-Positivliste
(2, 3, 14 für PMTiles; 15, 504, 505 nur zur Parallelkantenprüfung)
wird **nicht vor der Voronoi-Zuordnung angewendet**: Ein vorzeitiges
Entfernen würde die geometrische Partition fachlich verändern.

Der GIP2-Originaldownload in
`/mnt/c/Users/peter/Downloads/gip_network_ogd.gpkg`
wird ausschließlich im SQLite-Modus `mode=ro&immutable=1`
gelesen und weder kopiert noch verändert.

Die neuen Implementierungsänderungen sind zunächst nur per Code-Review
beurteilt; auf ausdrücklichen Wunsch wurden **keine zusätzlichen Tests
oder Wiener Datenläufe gestartet**.
