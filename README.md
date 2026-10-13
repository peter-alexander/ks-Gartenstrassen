# Wiener Gartenstraßen – datenbasierte Bestandsanalyse

Wir suchen anhand nachvollziehbarer Flächen- und später Kronenkennzahlen bestehende Straßenabschnitte, die dem Charakter von Gartenstraßen nahekommen. Die derzeitige Phase ist **Datenvorbereitung und Validierung** – noch keine fertige Gartenstraßen-Klassifikation.

## Datenbasis: vollständige FMZK als lokales GeoPackage

**Kanonische Quelle:** `FMZK_WIEN_GP.gpkg`, Layer `FMZK_WIEN_20260112`.

Laut `ogrinfo` vom 13.10.2026:

- 2.700.160 Features, Geometrie-Layer vom Typ `Unknown (any)` mit gekrümmten Polygonen;
- Projektion **EPSG:31256** (MGI / Austria GK East), metrisch;
- Geometriespalte `geom`, Feature-ID-Spalte `id`;
- fachliche Attribute unter anderem `F_KLASSE`, `F_KLASSE_TEXT`, `KLASSE_SUB`, `KLASSE_SUB_TEXT` und `FMZK_ID`.

**Wichtig:** Das gesamte Verzeichnis `data/` ist absichtlich von Git ausgeschlossen. Rohdaten und berechnete Ausschnitte liegen nur lokal. GitHub Actions benötigt sie nicht und führt keine Datenabrufe durch.

## Schritt 1: Testausschnitt extrahieren

Der gewählte Ausschnitt `16.361012,48.221226,16.366948,48.224902` bleibt bestehen. Er wurde gezielt ausgewählt, weil darin Grünflächen und Bäume im Verkehrsraum sichtbar sind.

Voraussetzungen (Ubuntu/WSL):

```bash
sudo apt install gdal-bin
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-analysis.txt
```

Das Extraktionsskript sucht `FMZK_WIEN_GP.gpkg` automatisch unter `data/`, `data/raw/` und im Projektverzeichnis:

```bash
.venv/bin/python scripts/extract_fmzk.py
```

Alternativ bei beliebigem Speicherort:

```bash
.venv/bin/python scripts/extract_fmzk.py --source "/voller/pfad/FMZK_WIEN_GP.gpkg"
```

Oder ein anderer kleiner Testausschnitt:

```bash
.venv/bin/python scripts/extract_fmzk.py --bbox 16.361012,48.221226,16.366948,48.224902 --overwrite
```

Die Ausgabe befindet sich unter:

- `data/processed/fmzk_test.gpkg` (Layer `fmzk`, EPSG:31256);
- `data/processed/fmzk_test.json` (Quelle, Datum, BBOX, Feature-Anzahl, wichtige Verarbeitungsparameter).

Zur Kontrolle:

```bash
ogrinfo -ro -so -al data/processed/fmzk_test.gpkg
```

Die Ausgabe enthält **alle FMZK-Klassen**, also nicht nur `Verkehr 1`/`Verkehr 2`, sondern auch die für uns relevanten Grünflächen.

### Technische Vorgehensweise

1. Mit einem räumlichen Filter (`ogr2ogr -spat`) nur die im Testbereich liegenden Originalfeatures lesen. Wenn vorhanden, verwendet GDAL den GeoPackage-RTree.
2. Gekrümmte Originalgeometrien (`CurvePolygon`) mit `-nlt CONVERT_TO_LINEAR` in lineare Geometrien konvertieren. Ohne Koordinatentransformation in dieser Stufe; beide GeoPackages bleiben in EPSG:31256.
3. Die WGS84-BBOX entlang ihrer vier Kanten verdichten, nach EPSG:31256 transformieren und erst dann mit `-clipsrc` exakt zuschneiden. Dadurch ist es **kein bloßer MBR-Zuschnitt** im projizierten CRS.
4. Die ursprünglichen FMZK-Attribute samt Feature-ID erhalten, einen räumlichen Index für das Ergebnis erstellen und die Zahl der Features prüfen.

Die Originaldatei wird **nie verändert**. Zwischen-Dateien werden nur temporär erzeugt und bei Ende des Vorgangs entfernt. Eine bereits vorhandene Ausgabe wird ohne `--overwrite` nicht ersetzt.

Falls bei der Umwandlung oder dem Zuschnitt tatsächlich ein ungültiges Originalpolygon einen Fehler verursacht, prüfen wir **erst die konkrete Fehlermeldung und das betroffene Feature**. Nur dann steht die explizite Option `--make-valid` zur Verfügung. Sie fordert eine Reparatur in der ersten Stufe an; mögliche geometrische Veränderungen müssen fachlich kontrolliert werden.

## Schritt 2: Flächenstatistik aller FMZK-Klassen

Nach erfolgreicher Extraktion (2.401 Features im gewählten Testausschnitt) wird **direkt aus dem lokalen GeoPackage** analysiert:

```bash
.venv/bin/python -m scripts.analyze_gpkg
```

Der Befehl erzeugt ausschließlich lokale Dateien unter `data/processed/analysis/`:

- `fmzk_klassen.csv`: Objektanzahlen sowie **Flächen in m²** je `F_KLASSE` inklusive der originalen `F_KLASSE_TEXT`-Bezeichnungen.
- `fmzk_report.json`: Geometrietypen, dokumentierte Reparaturen, Klassentext-Konflikte, geometrische Überlagerungen und Kontrolle des Zuschnitts.

Die Auswertung liest GeoPackage-Geometrien direkt aus SQLite: der GeoPackageBinary-Header wird entfernt und der WKB-Teil mit Shapely ausgewertet. **Es wird weder ein WFS noch ein GeoJSON-Zwischenschritt benötigt.** Die Flächen werden im unveränderten metrischen EPSG:31256 ermittelt. Überschneidende Polygone werden innerhalb jeder Klasse geometrisch vereinigt; etwaige Überlagerungen zwischen Klassen werden separat ausgewiesen.

Die BBOX-Grenze wird mit den Metadaten der Extraktion überprüft. Fehlende Klassen, unerwartete Geometrietypen oder nicht reparierbare Polygonfehler werden nicht stillschweigend verworfen. Falls ungültige Quellgeometrien repariert werden, werden Feature-ID und Grund im Bericht festgehalten.

**Wichtig:** Die Prozentspalte ist der Flächenanteil an der **gesamten Test-BBOX**. Sie ist **noch kein Grünanteil im öffentlichen Straßenraum**: Dieser braucht erst eine fachlich geprüfte Straßenflächenabgrenzung.

## Schritt 3: Öffentlichen Straßenraum vorläufig abgrenzen

Die Straßenraum-Analyse ist absichtlich **eine Sichtung**, keine automatische Zuweisung aller anliegenden Flächen zum Straßenraum.

```bash
.venv/bin/python -m scripts.analyze_street_space
```

**Ergebnisse nur lokal** in `data/processed/street_space/`:

- `strassenraum_kern.geojson`: geometrische Vereinigung der sicher erkennbaren öffentlichen Verkehrsflächen (Klassen **21 Fahrbahn, 23 Gehsteig, 24 Fußgängerzone, 33 ruhender Verkehr, 39 sonstige Verkehrsfläche**), WGS84.
- `strassenraum_pruefung.geojson`: einzelne Kernflächen, sämtliche Grün-Kandidaten **58/69**, unklare Flächen der **Klasse 59** und **private Kontextflächen 25/26/51**. Jede Geometrie hat `rolle`, `status` und relevante Kenngrößen. Andere FMZK-Klassen werden nicht exportiert.
- `strassenraum_kandidaten.csv`: pro Grün- bzw. unklarer Fläche Kennzahlen zu Abstand, Grenzkontakt und Umfeldnähe.
- `strassenraum_bericht.json`: Flächensummen pro Klasse und Lage-Status (jeweils als geometrische Vereinigung), verwendete Schwellen und eventuelle Geometriereparaturen.

Die Berechnung erfolgt in **EPSG:31256**, nur die GeoJSON-Ausgabe in **EPSG:4326**. Der Status ist ausschließlich eine räumliche Vorprüfung:

| Status | Bedeutung |
| --- | --- |
| `ueberlappt_kern` | Polygon überlappt die Kernfläche um mehr als 0,05 m² – geometrischen Konflikt prüfen |
| `grenzt_an_kern` | Randkontakt von mindestens 0,5 m entlang des Kerns, geprüft mit 0,25 m Toleranz |
| `nahe_kern` | Randkontakt zu kurz, aber innerhalb von 2 m zum Kern |
| `fern_vom_kern` | Kein entsprechender räumlicher Bezug zum Kern |

Die Randtoleranz/Distanz und Mindestkontaktlänge sind Parameter (`--randtoleranz-m`, `--nahe-m`, `--mindest-randkontakt-m`). Der Kennwert `flaeche_im_umfeld_pct` misst den Anteil des jeweiligen Kandidatenpolygons innerhalb des `--nahe-m`-Buffers um den Kern.

### Neu: Mehrseitige Einbettung und Kontakt zu Verkehrsflächenklassen

Für **58/69 (Grün)** und **59 (unklare befestigte Flächen)** wird zusätzlich zur bisherigen Abstandsanalyse gemessen, **an welchen Seiten** sie die Kernklassen 21, 23, 24, 33 und 39 berühren. Die Hauptparameter können angepasst werden:

```bash
.venv/bin/python -m scripts.analyze_street_space
# optional, nur zum Test alternativer Schwellen:
.venv/bin/python -m scripts.analyze_street_space --mindest-sektorkontakt-m 1.0 --normalen-probe-m 0.03
```

Die Analyse verwendet die **äußeren Normalrichtungen der kontaktierenden Polygonkanten** (8 Himmelsrichtungen). So wird eine lange einzelne Gartengrenze nicht irrtümlich als mehrseitig eingestuft, nur weil ihre Enden weit auseinanderliegen. Zur Richtungsermittlung prüft das Skript auf beiden Seiten jeder Kante einen Punkt in 3 cm Entfernung. Kanten ohne eindeutige Innen-/Außenseite werden nicht als positive Einbettungsindizien gewertet; ihre Länge steht unter `richtung_ungeklaert_m`.

Eine Richtungsgruppe zählt erst ab 0,8 m gemessener Kontaktlänge (einstellbar). Zwei Gruppen mit mindestens 135° Abstand gelten als gegenüberliegend; Kontakte an verschiedenartigen Verkehrsflächen sind ein zusätzliches Indiz. Die Daten bleiben explorativ:

| `einbettung` | Bedeutung |
| --- | --- |
| `mehrseitig_verschiedene_klassen` | Gegenüberliegende Kontakte zu **verschiedenen** Kernklassen (z. B. Fahrbahn und Gehsteig) |
| `mehrseitig` | Gegenüberliegende Kontakte, gegebenenfalls zur **gleichen** Kernklasse (z. B. Baumscheibe im Gehsteig) |
| `einseitig` | Kontakt an einer Seite bzw. nicht an gegenüberliegenden Seiten |
| `kein_deutlicher_randkontakt` | Unter den strengen Mindestwerten nicht ausreichend nachweisbar |
| `ueberlappung_pruefen` | FMZK-Kandidat überlappt die Kernflächen; topologischer Sonderfall |

In `strassenraum_kandidaten.csv` und `strassenraum_pruefung.geojson` stehen `einbettung`, `kontaktklassen`, `kontakt_sektoren`, `kontakt_rand_pct` sowie die **Kontaktlängen zu jeder Kernklasse** (`kontakt_21_m` usw.). Der JSON-Bericht enthält eine Statistik der Einbettungsgruppen.

**Wichtig:** Auch `mehrseitig` bedeutet **nicht** automatisch „öffentlicher Straßenraum“. Eine private Fläche kann von mehreren Verkehrsflächen umgeben sein; schmale öffentliche Grünstreifen können umgekehrt nur einseitig angrenzen. Die Schwellenwerte sind zunächst Testwerte, keine fachlich validierten Klassifikationsgrenzen. Wir überprüfen die Ergebnisse anhand echter Beispiele, bevor wir Flächen in Straßenraum-Prozentanteile übernehmen.

**Wichtig:**
- Auch `grenzt_an_kern` ist **keine Bestätigung**, dass die ganze Fläche öffentlich ist. Insbesondere große private Grundstücke können an Gehsteige grenzen.
- Klasse **39** wird nach fachlicher Prüfung als öffentlicher Straßenraum-Kern berücksichtigt. Klasse **59** (befestigte Fläche) ist hingegen nicht automatisch öffentliche Verkehrsfläche. Klasse 51 (Innenhof) und private Verkehrsflächen 25/26 bleiben Kontext, keine Kandidaten.
- Der Kern ist eine **Teilmenge** des Straßenraums; Verkehrsinseln, sonstige öffentliche Flächen und Grünstreifen sind damit noch nicht vollständig erfasst.
- Deshalb gibt es bewusst **noch keinen Grünanteil pro Straße** und keine Grünfläche / Kernfläche als vermeintlich gültigen Anteil.
- Die Ergebnislayer in QGIS öffnen oder in die Kartensammlung importieren. Verdächtige Flächen (z. B. Klasse 59 und große angrenzende Klasse-58-Polygone) anhand des Orthofotos/der FMZK überprüfen. Danach den exakten Straßenraum festlegen.

### Rolle der Baublöcke in späteren Analyseschritten

Baublöcke können die Zugehörigkeit einer Fläche zum Straßenraum **nur als räumlicher Hinweis** unterstützen. Ihre generalisierten Geometrien können gegenüber der FMZK um mehrere Meter abweichen. Deshalb werden sie **nicht als harte Schnitt- oder Ausschlussmasken** eingesetzt. Insbesondere schmale Grünstreifen, Baumscheiben und Parkspurbegrünungen dürfen nicht durch einen schematischen Baublock-Zuschnitt verloren gehen.

Für den späteren Zuordnungsschritt werden Nachbarschaften zu Fahrbahn/Gehsteig, Lage zwischen verschiedenen Verkehrsflächen und ggf. ein unsicherer Grenzbereich untersucht. Auch eine zwischen Kernflächen liegende Grünfläche wird nicht ohne Plausibilitätsprüfung als öffentlich klassifiziert. Die exakte Breite eines Toleranzbereichs wird erst anhand von überprüften Beispielen gewählt; Baublöcke werden in der jetzigen Pipeline noch **nicht** geladen.

## Synchronisierung des Quellcodes

Das ausführbare Skript `scripts/update-and-sync.sh` synchronisiert `main` bidirektional: Es committet **alle nicht ignorierten** lokalen Änderungen, holt `origin/main`, rebased lokale Commits, pusht und kontrolliert anschließend den Stand.

```bash
./scripts/update-and-sync.sh
# optional mit eigener Commit-Nachricht:
./scripts/update-and-sync.sh --message "Beschreibung der Änderungen"
```

**Vor der ersten Verwendung nach dieser Umstellung** einmal `git pull --ff-only` ausführen, damit die aktuellen Ignore-Regeln bereits lokal wirken, **bevor** das Skript `git add -A` aufruft. Es ignoriert `/data/` sowie `*.gpkg` und GeoPackage-Journaldateien auch außerhalb von `data/`. Der vollständige FMZK-Datensatz und alle Auswertungen bleiben lokal.

Zur Kontrolle: `git status --short` und `git ls-files '*.gpkg' 'data/**'`. Der zweite Befehl sollte keine Dateien zeigen. Einträge, die bereits von Git verfolgt werden, werden durch `.gitignore` nicht nachträglich entfernt.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```

GitHub Actions: [GeoPackage-Code-Tests](https://github.com/peter-alexander/ks-Gartenstrassen/actions/workflows/tests.yml). Der Workflow prüft ohne heruntergeladene Geodaten die Funktionen und den Extraktionsaufruf. **Eine vollständige Real-Daten-Extraktion kann nur auf einem Rechner mit dem lokalen GeoPackage und GDAL geprüft werden.**

## Älterer WFS-Versuch

`scripts/fetch_fmzk.py` und `scripts/analyze_fmzk.py` bleiben vorläufig als experimenteller Nachvollziehbarkeitsnachweis erhalten. **Sie gehören nicht mehr zur aktuellen Verarbeitung und sollen nicht ausgeführt werden.** Der WFS-Workflow wurde entfernt. Die damals lokal erzeugten beiden GeoJSON-Dateien werden nicht mehr gebraucht.

## Nächste Schritte

1. Extrahiertes GeoPackage prüfen: Feature-Anzahl, Flächenklassen, Geometrien und Quellenbezug.
2. Flächenbericht für den neuen Layer `fmzk` anhand der Kartendarstellung kontrollieren (Klassentexte, Geometrien, Überlagerungen und Grünflächen).
3. Öffentliche Straßenflächen von privaten Höfen und sonstigen Flächen trennen. Erst danach Kennzahlen je Straßensegment bestimmen.
4. Kandidaten aus `scripts.analyze_street_space` räumlich prüfen, öffentliche Straßenraumgrenzen festlegen und erst dann Bodenbegrünung und Kronenüberschirmung unabhängig voneinander je Abschnitt berechnen.

Datenquelle: **Stadt Wien – data.wien.gv.at**, gemäß [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.de). 
