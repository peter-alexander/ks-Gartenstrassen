# Wiener Arbeitsdaten ins lokale Repository übernehmen

## Ziel

Der vollständige Wiener SIS/GIP2-Lauf liegt künftig unter **`<repo>/data/wien/`**.
Das gesamte bisherige Verzeichnis **`~/Gartenstrassen`** wird dorthin
verschoben, ohne den Inhalt auszudünnen oder zu ändern:

- `aoi/` – Wien-AOI
- `wfs-kacheln/` – vollständige SIS-WFS-Originalkacheln (XZ), Metadaten
- `sis-wien.sqlite` – deduplizierter stadtweiter SIS-Index
- `analysis/wien/` – GIP2-Index, Rastermanifest, Partitionen, GRM, QA, Auswertungen und Zwischendateien
- sämtliche sonstigen im Quellverzeichnis tatsächlich vorhandenen Dateien

Der Ordner `data/` ist **Git-ignored**. Die Dateien liegen damit physisch
innerhalb des lokalen Repositorys, werden aber **nicht nach GitHub hochgeladen**.
Die mehrere Gigabyte großen Geodaten sind bewusst kein Bestandteil der
Git-Versionshistorie; Code, Tests und Methodik gehören dagegen auf `main`.

## Vorgehen in WSL

Vorher eventuell noch laufende Wien-Analysen beenden, insbesondere
SQLite-Schreibprozesse. Beide Befehle aus dem Root des Repositorys ausführen:

~~~bash
git pull --ff-only

# Prüft Quellverzeichnis, Gesamt-Wien-AOI, Rasterhash und GIP2-Index.
# Verändert noch nichts.
bash scripts/migrate-wien-data-into-repo.sh

# Erst nach erfolgreicher Prüfung das komplette Verzeichnis verschieben.
bash scripts/migrate-wien-data-into-repo.sh --apply
~~~

Die Migration verweigert einen bereits existierenden Zielordner,
eine fehlende Quellstruktur, eine Testgebiets-AOI oder einen nicht
zum Manifest passenden GIP-Index. Vorher und nachher werden dieselben
methodischen Prüfkriterien verwendet. Das ursprüngliche
`raster.json` bleibt bytegenau unverändert, damit bestehende
SHA-256-Abhängigkeiten erhalten bleiben. Die Wiener Pipeline kann mit
der lokalen AOI-Kopie `analysis/wien/aoi.geojson` auch nach dem
Pfadwechsel das originale Manifest erneut validieren.

Ein Umzug auf ein anderes Dateisystem kann länger dauern; den Prozess
nicht abbrechen. Fehler beim Verschieben oder Prüfen zunächst diagnostizieren;
keine vorhandenen Quelldaten löschen.

## Komplette Parallelkantenanalyse ausführen

~~~bash
bash scripts/run-gip-parallel-wien.sh
~~~

Der Befehl nutzt ohne zusätzlichen Pfadparameter **den gesamten**
Index in `data/wien/analysis/wien/gip.sqlite`. Die obligatorische
Vollständigkeitsprüfung verhindert eine Auswertung der bisherigen
Alsergrund-Testkachel. Die Resultate werden geschrieben nach
`data/wien/analysis/wien/gip-parallel-20m/`.

Für spätere komplette SIS-Wien-Läufe ist ebenso `data/wien` der
neue Standard von `scripts/run-sis-v2-wien.sh` und
`scripts/sis_wien_index.py`. Damit werden keine neuen Dateien
stillschweigend unter `/mnt/e/Gartenstrassen` angelegt.

## Bereinigung früherer Teststände

**Nicht das ganze `data/` oder `data/wien/` löschen.** Beide
enthalten möglicherweise einmalig abgerufene und kostspielig
berechnete Originalkacheln, GeoPackages und SQLite-Zwischenstände.
Das bisherige Quellverzeichnis `~/Gartenstrassen` entfällt durch
den erfolgreichen Umzug selbst. Alte Testdateien innerhalb anderer
`data/processed/`-Verzeichnisse können anschließend nach Inspektion
gezielt entfernt werden.

Für eine erste Inventur:

~~~bash
du -h --max-depth=3 data/processed 2>/dev/null | sort -h
find data/processed -mindepth 1 -maxdepth 3 -type d 2>/dev/null | sort
~~~

Typische **potenziell historische**, aber nicht automatisch zu
löschende Verzeichnisse sind `data/processed/sis-v2-run/`,
`data/processed/wienweit/alsergrund/` und
`data/processed/strassenabschnitte/`. Welche davon auf deinem
Dateisystem bestehen, lässt sich nur dort feststellen. Erst nach
Bestätigung des vollständigen Wiener Datenstandes entscheiden,
welche konkreten Testordner entfallen sollen. Die alte Pilot-*Software*
(u. a. `run-sis-v2-pilot.sh`) bleibt notwendig, weil sie vom
Wien-Lauf selbst verwendet wird.
