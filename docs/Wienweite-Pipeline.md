# Wienweite Pipeline: vorbereitete Phasen 1 und 2

**Stand 14.10.2026:** Technische Infrastruktur implementiert und synthetisch getestet. **Noch kein echter Bezirks- oder Wien-Gesamtlauf** mit vollständigen regionalen Daten. Der erfolgreiche kleine Modul-6-Test und seine V0-Daten bleiben unverändert.

## Gleichbleibende Methodik

Die vorläufige Modul-2-Straßenraumabgrenzung verwendet weiterhin FMZK-Kern 21/23/24/33/39 und bei anderen Flächen die BEV-Kataster-nfl-Klassen 95/65 mit mindestens 95 % Deckung. Unklare Objekte werden konservativ nicht zugeordnet.

GIP-V0 verwendet **5 m Abtastung, 7 m Knotenradius bei Grad >= 3, 25 m maximalen Achsabstand, FOW=3 für reguläre Abschnitte**. Kreuzungen und Sonderachsen bleiben getrennt. V1-Eckpunkt-Erkennung wird nicht weiterentwickelt.

## Neue Programme

| Programm | Aufgabe |
| --- | --- |
| scripts/wienwide_grid.py | Festes Raster in EPSG:31256, AOI-/Manifest-Hash, Kachelkontrolle |
| scripts/wienwide_gip.py | WFS-Abrufe kachelweise mit Halo, Quelldaten-Cache, globale GIP-ID-Deduplizierung, SQLite-Graph und RTree-Index |
| scripts/wienwide_street.py | Bestehende FMZK-/Kataster-Regeln auf lokale Quellkacheln anwenden und Ergebnis direkt als metrisches WKB/SQLite speichern |
| scripts/wienwide_partition.py | Voronoi-V0 anhand globaler 5-m-Stützpunkte kachelweise rechnen, Flächenbilanz und Ergebnis-Fragmente nach GIP-ID in SQLite speichern |
| scripts/wienwide_benchmark.py | Quellabdeckung, Kachel-Laufzeiten, partielle/vollständige Resultate und Flächenbilanz als JSON |

Der Halo beträgt zunächst **75 m**, die Kernkachel **1000 × 1000 m**. Es sind Benchmarkparameter, keine endgültigen Werte. Die Kachelgrenzen dienen ausschließlich der Berechnung; globale Site-IDs und Knotengrade stehen vor der Aufteilung fest. Kein GeoJSON-Rundweg für die maßgeblichen metrischen Flächen.

## Voraussetzungen

1. Bereits vorhandene vollständige FMZK-Originaldatei FMZK_WIEN_GP.gpkg (EPSG:31256).
2. **Echte** AOI-Polygone als GeoJSON/WGS84. Zunächst ein dicht bebauter Bezirk wie Alsergrund und ein weitläufigerer wie Donaustadt. Diese AOI-Dateien müssen beschafft/validiert werden; im Repository werden keine erfundenen Bezirksgrenzen bereitgestellt.
3. GIP-WFS der Stadt Wien und BEV-Kataster-z16 dürfen abrufbar sein; Cache-Daten werden wiederverwendet.
4. Lokaler Datenträger für rasterweise FMZK, Kataster, GIP und SQLite. Keine belastbare Speicher-/Laufzeitschätzung vor Realtest.

## Beispiel: Bezirk Alsergrund

Die Pfade sind Beispiele und setzen eine echte lokale Bezirks-AOI voraus.

### 1. Raster erstellen

~~~bash
git pull --ff-only
.venv/bin/python -m scripts.wienwide_grid \
  --aoi data/raw/bezirke/alsergrund.geojson \
  --tile-m 1000 --halo-m 75 \
  --out data/processed/wienweit/alsergrund/raster.json
~~~

Das Raster ist fix in EPSG:31256 und vollständig auf die echte AOI beschnitten. Bei großen/fehlerhaften Kataster-Kacheln einen separaten **500-m-Plan** erstellen, nicht heimlich nur die Hälfte der Fläche auswerten.

### 2. GIP-Quellprobe, vollständiger Abruf und Index

~~~bash
.venv/bin/python -m scripts.wienwide_gip fetch \
  --manifest data/processed/wienweit/alsergrund/raster.json \
  --out-dir data/processed/wienweit/alsergrund/gip_fragmente \
  --limit-tiles 1

.venv/bin/python -m scripts.wienwide_gip fetch \
  --manifest data/processed/wienweit/alsergrund/raster.json \
  --out-dir data/processed/wienweit/alsergrund/gip_fragmente

.venv/bin/python -m scripts.wienwide_gip index \
  --manifest data/processed/wienweit/alsergrund/raster.json \
  --fragments data/processed/wienweit/alsergrund/gip_fragmente \
  --out data/processed/wienweit/alsergrund/gip.sqlite
~~~

Der Index lässt sich **nicht** aus unvollständigen Fragmenten erstellen. Leere WFS-Kacheln sind nach expliziter Prüfung erlaubt; Limitüberschreitungen, Duplikatkonflikte, falsches CRS oder fehlende GIP-Knoten am AOI-Rand führen zum Abbruch. Die Quelle und der Index bleiben unverändert.

### 3. FMZK und Kataster

Zunächst die tatsächliche erste Tile-ID aus raster.json auswählen (der Platzhalter ist kein ausführbarer Name).

~~~bash
.venv/bin/python -m scripts.wienwide_street fetch-inputs \
  --manifest data/processed/wienweit/alsergrund/raster.json \
  --input-root data/processed/wienweit/alsergrund/eingaben \
  --fmzk-source data/raw/FMZK_WIEN_GP.gpkg \
  --kataster-cache data/cache/kataster \
  --only 'TILE-ID-AUS-MANIFEST'
~~~

Ist diese Probe korrekt, den Aufruf **ohne --only** wiederholen. Das Kataster-Skript verwendet dieselbe z16- und nfl-Auswertung wie das Testgebiet. Vorhandene BEV-Tiles werden gecacht; es werden keine unbekannten Nutzungen stillschweigend als Straße gerechnet.

~~~bash
.venv/bin/python -m scripts.wienwide_street build \
  --manifest data/processed/wienweit/alsergrund/raster.json \
  --input-root data/processed/wienweit/alsergrund/eingaben \
  --out-root data/processed/wienweit/alsergrund/strassenraum
~~~

Die resultierende street.sqlite liegt **je Tile** mit metrischer WKB-Geometrie und FMZK-/Kataster-Prüfsummen vor. Eine tatsächlich straßenraumfreie Kachel wird nach vollständiger Quellenauswertung explizit als leer markiert; fehlende Quelldaten sind dagegen ein Fehler.

### 4. V0 kachelweise rechnen und wiederaufnehmen

~~~bash
.venv/bin/python -m scripts.wienwide_partition \
  --manifest data/processed/wienweit/alsergrund/raster.json \
  --gip-index data/processed/wienweit/alsergrund/gip.sqlite \
  --street-root data/processed/wienweit/alsergrund/strassenraum \
  --out data/processed/wienweit/alsergrund/aufteilung.sqlite \
  --limit-tiles 1

.venv/bin/python -m scripts.wienwide_partition \
  --manifest data/processed/wienweit/alsergrund/raster.json \
  --gip-index data/processed/wienweit/alsergrund/gip.sqlite \
  --street-root data/processed/wienweit/alsergrund/strassenraum \
  --out data/processed/wienweit/alsergrund/aufteilung.sqlite
~~~

Vollständige Kacheln mit unveränderten Prüfsummen werden übersprungen. Die Ausgabe enthält pro Kachel und GIP-ID separate metrische Polygonfragmente und die drei Kategorien ungeklärter Flächen. **PARTIELL** ist nicht gleichbedeutend mit einem fertigen Bezirksresultat.

### 5. Benchmark protokollieren

~~~bash
.venv/bin/python -m scripts.wienwide_benchmark \
  --manifest data/processed/wienweit/alsergrund/raster.json \
  --inputs data/processed/wienweit/alsergrund/eingaben \
  --gip-fragments data/processed/wienweit/alsergrund/gip_fragmente \
  --street-root data/processed/wienweit/alsergrund/strassenraum \
  --gip-index data/processed/wienweit/alsergrund/gip.sqlite \
  --partition-db data/processed/wienweit/alsergrund/aufteilung.sqlite \
  --out data/processed/wienweit/alsergrund/benchmark.json
~~~

Anschließend denselben Ablauf mit eigener AOI und getrennten Pfaden für Donaustadt durchführen. Erst nach beiden echten Durchläufen lassen sich Speicherbedarf, Quellverfügbarkeit, Flächenbilanz und Laufzeiten vergleichen.

## Qualitäts- und Skalierungsgrenzen

- Die Voronoi-Ergebnisse werden pro Kachel gegen den Original-Straßenraum geprüft. Gemeinsam verwenden sie **globale GIP-Stützpunkte**, sodass selbst an einer Kreuzung auf der Kachelgrenze dieselbe Flächenzuordnung wie in einem globalen V0-Lauf entstehen soll. Die synthetischen Regressionen prüfen die Übereinstimmung mit der bisherigen V0; **Realtest steht aus**.
- Alle Kacheln sind auf die AOI-Kerne beschnitten; keine Übertragung einer 75-m-Halo-Fläche in die endgültige Flächenbilanz.
- GIP-ID-Dubletten mit abweichender Geometrie führen zu einem Fehler. Nichts wird mit einer neuen ID ersetzt.
- Der Quellstand muss konsistent sein. Die Katalog-/Daten-SHA werden zwischen Läufen geprüft. Wegen WFS-Änderungen während eines sehr langen Abrufs bleibt eine **zeitliche Snapshot-/Änderungsprüfung vor dem endgültigen Wien-Lauf** erforderlich.
- Die bisherige Katasteranalyse nutzt BEV-z16 mit Grenzwerten für Kacheln und Grundstücke. Sie muss bei schwierigen Pilotkacheln anhand echter Fälle weiter abgesichert werden.
- Der Benchmark-Zeitwert bezieht sich **nur auf lokale Voronoi-Partitionierung samt Kachel-Lesen**, **nicht** auf sämtliche FMZK-/BEV-/GIP-Downloads oder Kronenmethoden.
- Baumkronen A/B/C und Bodenbegrünung je GIP-ID **wienweit berechnen**, insbesondere GRM-WMS kachelweise korrekt in metrischer Auflösung zu verwenden, ist ein **nächster eigener Schritt**. Die bestehende GRM-Maske ist nur für kleine Rastergrößen ausgelegt.
- **Keine** fertige Kartenkachel-/MBTiles-Erzeugung oder automatische Gartenstraßen-Klassifizierung in diesem Schritt.

Die bisherigen 45 Testabschnitte und ihre Kennzahlen bleiben unverändert. Rohdaten liegen lokal unter data/ (Git-ignored) und gehören nicht in das öffentliche Repository.
