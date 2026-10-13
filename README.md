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
4. Bodenbegrünung und Kronenüberschirmung unabhängig voneinander berechnen, mit bekannten positiven und negativen Beispielen validieren.

Datenquelle: **Stadt Wien – data.wien.gv.at**, gemäß [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.de). 
