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
- `work/`: SIS-/GIP-Indizes, abgeleiteter Kanten-Graph,
  Straßenräume, Partitionen, Kronenmasken
- `output/`: **`gip_abschnitte.geojson` und `gartenstrassen.pmtiles`**,
  außerdem `gip_abschnitte.csv`, `gip_kanten_zuordnung.csv`,
  `bericht.json` und `freigabe.json`
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

## GIP-Kantenvereinigung vor der Flächenzuordnung

Nach `gip-index` läuft automatisch `gip-merge`. Dieser Schritt baut
`work/wien/gip_merged.sqlite` als **neuen abgeleiteten Graphen**;
`work/wien/gip.sqlite` sowie
`/mnt/c/Users/peter/Downloads/gip_network_ogd.gpkg` bleiben unverändert.

Die bereits vorhandene 20-m-Parallelanalyse liefert die Kandidaten
(85 % der kürzeren / 60 % der längeren Achse sowie höchstens 25°
Richtungsabweichung). Bei zwei Straßenachsen wird zusätzlich ein
übereinstimmender, nicht leerer Straßenname verlangt. Fuß-/Radwege
(FOW 15/504/505) können nur einer **eindeutig** identifizierten
Straßengruppe zugeordnet werden; eine unsichere Mehrfachzuordnung bleibt
unverändert. Fußgängerzonen (FOW 14) werden nicht mit Fahrbahnen
(FOW 2/3) vereinigt. Verknüpfungsketten werden nicht blind geschlossen:
Straßenmitglieder benötigen direkte parallele Evidenz zueinander.

Für jede Gruppe bleibt die längste Straßenachse als repräsentierende
Original-GIP-ID erhalten. Die geometrische Gruppe enthält die
**Original-Linien aller Mitglieder**, keine erfundene Mittellinie.
Die Positionen und die Anzahl der globalen 5-m-Voronoi-Sites
bleiben unverändert, aber ihre Zuordnung erfolgt auf die gemeinsame
repräsentative Achsen-ID. Diese Zuordnung wird **vor** der
Voronoi-Partitionierung verwendet.

Die Originaldaten sind vollständig über `original_axes` und
`merged_members` in der abgeleiteten SQLite sowie über die
dauerhafte `output/gip_kanten_zuordnung.csv` nachvollziehbar.
Die exportierten GeoJSON-/CSV-Abschnitte führen außerdem die
Spalte/Eigenschaft `original_gip_ids`.

Die bestehende Querschnittsroutine kürzt mehrteilige Achsgeometrien
bewusst **nicht ohne eindeutige Richtung**. Gruppen aus mehreren
Originalkanten werden deshalb nicht durch eine ungeprüfte neue
Querschnittsheuristik verkleinert. Die bisherige
Flächenbilanzprüfung bleibt Pflicht.

**Wichtig:** Dies ist eine neue Auswertungsmethode. Ein bereits fertiger
Wien-Lauf ohne Kantenvereinigung ist kein kompatibler Checkpoint; seine
Zwischendaten dürfen nicht stillschweigend weiterverwendet werden.
Der bislang erfolgreich erzeugte Output bleibt bestehen, bis ein
vollständiger neuer Lauf fachlich geprüft und veröffentlicht wurde.
