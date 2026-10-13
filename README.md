# Wiener Gartenstraßen – Bestandsanalyse (Prototyp)

Ziel: Wiener Straßenabschnitte anhand ihrer tatsächlichen Grünflächen, Baumkronenüberschirmung und Nutzung des Straßenraums nachvollziehbar untersuchen. **Noch keine fertige Gartenstraßen-Klassifikation.**

## Schritt 1 – Kleine FMZK-WFS-Probe (Verkehr 1 + 2)

Die Stadt Wien stellt FMZK-Daten als Gesamt-GeoPackage sowie als separate WFS-Layer bereit. Der Prototyp fragt zunächst nur folgende Layer ab:

- `ogdwien:FMZKVERKEHR1OGD`
- `ogdwien:FMZKVERKEHR2OGD`

Standard-Bounding-Box (WGS84, `west,süd,ost,nord`): `16.361012,48.221226,16.366948,48.224902`.

Das Abrufskript verwendet WFS 1.0.0 (EPSG:4326, Längengrad/Breitengrad) und maximal 5.000 Features pro Layer. Erreicht die Rückgabe die Grenze, wird ausdrücklich abgebrochen. Bitte für Tests nur kleine Ausschnitte verwenden.

### Installation und Ausführung

Benötigt: Python 3.12 oder neuer (GIS-Pakete auch für andere geeignete Versionen erhältlich).

```bash
python3 -m pip install -r requirements-analysis.txt
python3 -m unittest discover -s tests -v
python3 scripts/fetch_fmzk.py
python3 -m scripts.analyze_fmzk
```

Der letzte Befehl arbeitet **ausschließlich mit den bereits lokal heruntergeladenen GeoJSON-Dateien** und benötigt keinen Netzwerkzugriff.

Alternativ: `python3 scripts/fetch_fmzk.py --bbox 16.355,48.192,16.360,48.196` für einen anderen kleinen Ausschnitt, oder `--format both` für zusätzliche Shapefile-ZIPs. Die Analyse verwendet immer die zum Abruf gehörende BBOX aus dem `manifest.json`.

### Ergebnisse

Nicht versionierte Dateien:

- `data/raw/fmzk_verkehr1.geojson` und `fmzk_verkehr2.geojson`: unveränderte WFS-Features;
- `data/raw/manifest.json`: Quelle, BBOX, Abrufzeitpunkt, Feature-Anzahl und Klassenverteilung;
- `data/processed/fmzk_klassen.csv`: pro Layer und `F_KLASSE` Anzahl und Fläche in m²;
- `data/processed/fmzk_report.json`: Metadaten, Gesamtfläche der BBOX, gesamte Polygonabdeckung und mögliche Überlagerungen;
- `data/processed/fmzk_ausschnitt.geojson`: **auf die BBOX zugeschnittene** Features mit `QUELLE`, `FMZK_TEXT`, `AREA_M2` und `GEOM_FIX`, direkt in QGIS zu öffnen.

Die Flächenberechnung erfolgt durch Transformation nach **EPSG:31256 (MGI / Austria GK East)**. Dabei werden die Polygone zuerst auf die Bounding Box zugeschnitten. Der Flächenwert je Klasse basiert auf der geometrischen Vereinigung ihrer Features, um Überlagerungen **innerhalb** derselben Klasse nicht mehrfach zu zählen. Überlappungen **zwischen** Klassen beziehungsweise Layern werden separat ausgewiesen. Ungültige WFS-Polygone werden mit `shapely.make_valid` in gültige Polygonflächen überführt. Alle Reparaturen werden unter `geometry_repairs` in `fmzk_report.json` mit Feature-ID und Fehlerursache protokolliert; die Originaldateien bleiben unverändert. Falls keine gültige Polygonfläche rekonstruiert werden kann, bricht die Analyse ab. Unbekannte `F_KLASSE`-Codes sind ebenfalls Fehler. Die reparierten Geometrien müssen fachlich anhand der Karte kontrolliert werden.

**Achtung:** Der Prozentanteil in `fmzk_klassen.csv` bezieht sich auf die **gesamte Bounding Box**, keinesfalls auf die noch nicht ermittelte öffentliche Straßenfläche. Er ist **kein Grünanteil und kein Gartenstraßen-Ranking**.

### Erste Ergebnisse des WFS-Tests vom 13.10.2026

Erfolgreich abgerufen (gleiche Standard-BBOX): **264 Features Verkehr 1, 685 Features Verkehr 2**. Darunter sind u. a. 156 Objekte der Klasse 33 (ruhender Verkehr im öffentlichen Gut), aber auch 228 Objekte der Klasse 51 (Hof / Innenhof) und 201 der Klasse 59 (befestigte Fläche). Die WFS-Layergruppen sind also **nicht gleichbedeutend mit öffentlichem Straßenraum**. Objektzahlen sind keine Flächenanteile.

Die FMZK-Klassennamen sind durch das amtliche [Attribut- und Werteverzeichnis (PDF)](https://www.wien.gv.at/pdf/ma41/fmzk-attribute-wertebereiche.pdf) dokumentiert.

## Lokalen Git-Stand synchronisieren

`scripts/update-and-sync.sh` gleicht den lokalen `main`-Branch bidirektional mit `origin/main` ab. Nicht ignorierte lokale Änderungen werden dabei zuerst committet, anschließend werden Remote-Änderungen per Rebase eingespielt und der resultierende Stand gepusht. Bei Konflikten oder einer offenen Git-Operation bricht das Skript ab, ohne Historie zu überschreiben.

```bash
./scripts/update-and-sync.sh --message "Beschreibe meine Änderung"
```

## Datenqualität und fachliche Einschränkungen

1. WFS und Gesamt-GeoPackage stammen aus derselben FMZK-Produktfamilie, aber **Datenstand und identische Geometrien sind noch nicht verifiziert**.
2. Nur anhand von Verkehr 1/2 lässt sich die öffentliche Straßenfläche nicht zuverlässig abgrenzen. Dafür benötigen wir weitere Layer, die Straßensegmentierung und eine sorgfältige Behandlung von Privatflächen, Kreuzungen und Überlagerungen.
3. Für Grünflächen im Straßenraum sind insbesondere `FMZKGRUEN1OGD` / `FMZKGRUEN2OGD` sowie die fachliche Unterscheidung von Vegetation und bloßer Unversiegelung zu prüfen. Grünflächen in Innenhöfen gehören **nicht** automatisch zum Straßenraum.
4. Für Kronenüberschirmung benötigen wir das auswertbare Grünraummonitoring; aus Baumstandorten allein können wir Kronenflächen nicht exakt ableiten.
5. Der kleine WFS-Abruf ist **nicht** als Ganz-Wien-Download vorgesehen. Für die produktive Analyse ist das Gesamt-GeoPackage voraussichtlich geeigneter.
6. Die erzeugten Testdaten und Berichte werden nicht ins Repository eingecheckt. Über **GitHub Actions → FMZK-WFS-Test → Run workflow** können Tests, Abruf und Analyse auf einem Runner gestartet und als Artifact heruntergeladen werden.

Datenlizenz: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.de), Quellenangabe **Datenquelle: Stadt Wien – data.wien.gv.at**.

## Datenquellen

- [FMZK-Vektordaten/WFS – data.gv.at](https://www.data.gv.at/datasets/7cf0da04-1f77-4321-929e-78172c74aa0b?locale=de)
- [FMZK – Daten beziehen](https://www.wien.gv.at/stadtplanung/flaechen-mehrzweckkarte-daten-beziehen)
- [Flächen-Mehrzweckkarte – Produktinformation](https://www.wien.gv.at/stadtplanung/flaechen-mehrzweckkarte-produktinformation)

## Nächste Schritte

1. Flächenbericht und Kartendarstellung des Testausschnitts gegenprüfen (Geometrien, Löcher, Überlagerungen, Klasse 51/59).
2. Grün1/Grün2 abrufen und Datenqualität prüfen.
3. Straßensegmente sowie die tatsächliche Bezugsfläche „öffentlicher Straßenraum“ definieren und abgrenzen.
4. 10–20 bekannte positive/negative Beispiele als Validierungsfälle verwenden.
5. Grünanteil und Baumkronenüberschirmung getrennt berechnen und erst danach Klassifikation und Wien-Pipeline entwickeln.
