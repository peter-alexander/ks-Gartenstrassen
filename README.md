# Wiener Gartenstraßen – datenbasierte Bestandsanalyse

Wir suchen anhand nachvollziehbarer Flächen- und später Kronenkennzahlen bestehende Straßenabschnitte, die dem Charakter von Gartenstraßen nahekommen. Die derzeitige Phase ist **Datenvorbereitung und Validierung** – noch keine fertige Gartenstraßen-Klassifikation.

**Aktueller Arbeitsstand (13.10.2026):** Eine erste Aufteilung **aller FMZK-Flächen des Testgebietes** in `fmzk_strassenraum.geojson` und `fmzk_uebrige_flaechen.geojson` ist implementiert und wurde in der Kartensammlung visuell überprüft. Sie sieht im Übersichts- und Detailmaßstab bereits überzeugend aus, ist aber **noch nicht fehlerfrei und keine abschließend validierte bzw. rechtlich verbindliche Straßenraumgrenze**. Für die nächste Analysephase wird die Methode **vorläufig beibehalten**, nicht als endgültig erklärt.

**Ausführliche Dokumentation:** [Methodik und Arbeitsstand der FMZK-Kataster-Straßenraumabgrenzung](docs/Methodik-Strassenraum-FMZK-Kataster.md) – Datenquellen, Regeln, Prüfergebnisse, visuelle Kontrolle, bekannte Grenzen und weitere Schritte.

**Modularer Aufbau:** [Architektur und Datenschnittstellen](docs/Modulare-Architektur.md). Das Straßenraum-Erzeugungsverfahren (Modul 2) kann später ausgetauscht werden, ohne die Berechnung von Bodenbegrünung und künftiger Kronenüberschirmung anzupassen.


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

## Schritt 4: 25 FMZK-Polygone zur manuellen Prüfung auswählen

Aus der bestehenden Analyse werden **genau 25** ausgewählte Prüffälle erzeugt. Die Datenquelle bleibt dein lokales GeoPackage; **keine erneuten WFS-Abfragen**:



```bash
./scripts/update-and-sync.sh
.venv/bin/python -m scripts.sample_street_space
```

Verteilung der Stichprobe:

| Gruppe | Anzahl |
| --- | ---: |
| Klasse 69 – gegenüberliegende Kontakte zu verschiedenen Verkehrsflächenklassen | 5 |
| Klasse 69 – mehrseitig, ohne nachgewiesene gegenüberliegende verschiedene Klassen | 5 |
| Klasse 69 – einseitig | 3 |
| Klasse 69 – kein deutlicher Randkontakt | 3 |
| Klasse 58 – grenzt an den Straßenraum-Kern | 5 |
| Klasse 59 – mehrseitig, beide Einbettungsarten gemischt | 4 |

**Die Auswahl ist bewusst stratifiziert, nicht zufällig und nicht statistisch repräsentativ.** Innerhalb der Gruppen berücksichtigen wir kleine, große und (wo möglich) mittlere Polygone sowie unterschiedliche Lagen im Testausschnitt. Die Auswahl hängt nicht von der Reihenfolge im GeoJSON ab.

Die erzeugten Dateien stehen ausschließlich unter `data/processed/street_space/pruefstichprobe/`:

- `pruefbeispiele.geojson`: 25 Polygongeometrien in WGS84, alle vorhandenen Analyseattribute einschließlich `einbettung`, ergänzt um `pruef_nr` (1–25), `pruefgruppe`, die originale `FMZK_ID` als `fmzk_id` und weitere Quellattribute.
- `pruefbeispiele_punkte.geojson`: 25 Punkte **innerhalb** der Polygone zur leichteren Orientierung bei sehr kleinen Baumscheiben; die Nummer ist `pruef_nr`. Bei Bedarf separat laden.
- `pruefbeispiele.csv`: Tabelle mit IDs, Flächengrößen, Kontaktmerkmalen sowie **leeren Beurteilungsfeldern**.
- `pruefbeispiele_bericht.json`: Auswahlmethode und nachprüfbare Objektliste pro Gruppe.

### Sichtung in Kartensammlung oder QGIS

1. `pruefbeispiele.geojson` zusammen mit `strassenraum_kern.geojson` importieren, ein aktuelles Orthofoto als Hintergrund verwenden.
2. Wenn die kleinen Flächen schwer zu treffen sind, zusätzlich `pruefbeispiele_punkte.geojson` laden. `pruef_nr` dient zur Zuordnung zwischen Polygon und Tabellenzeile.
3. In **`pruefbeispiele.csv`** pro Zeile `pruefstatus` mit `strassenraum`, `kein_strassenraum` oder `unklar` ausfüllen; Beobachtungen unter `pruefnotiz` ergänzen. `offen` ist der Ausgangszustand.
4. Änderungen in der CSV erhalten und später gemeinsam auswerten. Für die ersten 25 Fälle reicht diese Tabelle; es ist noch keine automatische Klassifikation implementiert.

**Flächenpräzision:** Sehr kleine, gültige FMZK-Polygone können bei einer Anzeige mit zwei Nachkommastellen als `0,00 m²` erscheinen. Die Stichprobenauswahl verwendet für solche bereits erzeugten GeoJSONs die tatsächliche Geometriefläche in EPSG:31256; die Straßenraumanalyse exportiert künftig ungerundete Objektflächen. **Für die Korrektur muss `analyze_street_space` nicht erneut ausgeführt werden.**

**Schutz gegen Datenverlust:** Das Skript überschreibt bestehende Dateien standardmäßig nicht. Die Option `--overwrite` darf nur eine **noch unbewertete** Stichprobe ersetzen und verweigert die Überschreibung, wenn Bewertungen/Notizen in CSV oder Polygon-GeoJSON vorhanden sind. Alternativ `--out-dir` mit einem neuen Ausgabeverzeichnis wählen.

**Nicht behaupten:** Die Beurteilung einer bewusst ausgewählten Stichprobe liefert weder eine Fehlerrate für ganz Wien noch eine allgemeine Genauigkeit der Heuristik. Dafür wären später zusätzliche zufällig gezogene Kontrollfälle nötig.


## Schritt 5: Kataster-Grundstücke und vollständige Nutzung prüfen

In der **Kartensammlung** ist der aktuelle BEV-Kataster als Vector-Tile-Layer eingebunden:
`https://kataster.bev.gv.at/tiles/kataster/{z}/{x}/{y}.pbf`. Die Kacheln enthalten unter anderem `gst` (Grundstücke) und `nfl` (Nutzungsflächen). Wie dort verwendet, kann die vollständige Nutzungsbilanz eines bekannten Grundstücks separat über `https://kataster.bev.gv.at/api/gst/<kgez>/<gnr>/` abgerufen werden.

Die separate Analyse `scripts/analyze_kataster.py`:

1. Liest den **bisherigen FMZK-Testausschnitt** aus `data/processed/fmzk_test.gpkg` und berechnet den bestehenden Kern **21/23/24/33/39**.
2. Lädt die BEV-Kacheln auf **Zoomstufe 16**, einschließlich einer zusätzlichen Kachel rings um die Test-BBOX. Die GeoPackage- und Tile-Geometrien werden in **EPSG:31256** verschnitten. Kernflächen mit echtem Flächenschnitt identifizieren getroffene `gst`-Grundstücke anhand **Katastralgemeinde + Grundstücksnummer**.
3. Verwendet standardmäßig **nur bereits zwischengespeicherte** Antworten der Grundstücks-API. Falls vollständige Nutzungsbilanzen im Cache fehlen, bleibt die Grundstücksklasse **D**, während die in den Kacheln sichtbaren `nfl`-Nutzungsarten lediglich als vorläufiger Hinweis ausgegeben werden. Mit `--details` werden die fehlenden Grundstücksdaten online angefordert; bei HTTP 429/5xx oder Verbindungsproblemen stoppt der Skriptlauf weitere Detailabfragen.
4. Exportiert die `nfl`-Teilflächen zur Sichtkontrolle. Diese stammen weiterhin nur aus den verwendeten Kacheln und werden für die Klassifizierung **nicht** als vollständiger Flächennachweis verwendet.

Installation nach dem Synchronisieren und erster Durchlauf:


```bash
./scripts/update-and-sync.sh
.venv/bin/python -m pip install -r requirements-analysis.txt
.venv/bin/python -m scripts.analyze_kataster
```

**Während die BEV-Grundstücks-API ausfällt**, führt der obige Aufruf **keine Grundstücksdetail-Anfragen** aus. Vorhandene API-Antworten aus dem Cache können weiterhin A/B/C ermöglichen; sonst erscheint D mit zusätzlichem `tile_nutzungshinweis` (`nur_95_65_im_ausschnitt`, `gemischt_im_ausschnitt`, `keine_95_65_im_ausschnitt` oder `unvollstaendig_oder_unbekannt`). Dieser Hinweis basiert nur auf den verfügbaren Kacheln, **nicht** auf der Nutzung des ganzen Grundstücks.

Erst wenn der Endpunkt wieder funktioniert:

```bash
.venv/bin/python -m scripts.analyze_kataster --details
```

Der Online-Modus nutzt den Cache und unterbricht nach dem ersten HTTP-429-/Server-5xx- oder Netzwerkfehler weitere API-Anfragen. Mit `--refresh --details` werden bereits vorhandene Antworten erneut geholt; ohne diese Kombination bleiben die archivierten Antworten erhalten.

**Einstufung der ganzen Grundstücke anhand der BEV-API:**

| Klasse | Bedingung | Aussage |
| --- | --- | --- |
| **A** | Nur Nutzung 95 (Straßenverkehrsanlagen) und/oder 65 (Verkehrsrandflächen) | Hohe Plausibilität für Verkehrsraum; nicht rechtlich als öffentliche Straße bewiesen |
| **B** | Mindestens 95 oder 65, außerdem weitere Nutzungen (z. B. 41 Gebäude, 52 Gärten, 42 Parkplätze) | Gemischtes Grundstück, nur Teilflächen weiter prüfen |
| **C** | Kein 95/65, obwohl der FMZK-Kern das Grundstück schneidet | Widerspruch oder andere Nutzung; reine Parkplätze/Schienenverkehr als Sonderfall kenntlich |
| **D** | Detail-API nicht erreichbar, Nutzungsbilanz fehlt, Code unbekannt oder fehlerhaft | **Keine Entscheidung**; niemals automatisch als A behandeln |

Die Bezeichnung A steht für **hohe Plausibilität, nicht hohe rechtliche Autorität**: Kataster-Benützungsarten beweisen keine Eigentümerschaft oder straßenrechtliche Widmung. Für Gruppe B übernehmen wir **nicht das gesamte Grundstück**. Die FMZK bleibt die feinere Nutzungsgeometrie.

**Lokale Ausgaben** unter `data/processed/kataster/`:

- `kataster_grundstuecke.geojson`: vom Kern getroffene Grundstücksfragmente innerhalb der BBOX, eingefärbt nach `klasse` möglich.
- `kataster_nfl_ausschnitt.geojson`: Nutzungsflächen **nur innerhalb des verfügbaren Ausschnitts** (Eigenschaft `vollstaendig=false`); zur Kartenkontrolle, **nicht** als Nutzungsbilanz des Grundstücks.
- `kataster_grundstuecke.csv`: je Grundstück KG, Nummer, A/B/C/D, Kernüberschneidung, API-Nutzungscodes und Flächensummen sowie im Tile beobachtete `nfl.ns`-Codes und einen **vorläufigen `tile_nutzungshinweis`**.
- `kataster_bericht.json`: Gesamtstatistik, alle vollständigen API-Nutzungsbilanzen, Fehlermeldungen und Liste der verwendeten Kacheln.

Alle Abrufe werden lokal in `data/cache/kataster/` gespeichert. Dadurch ist der zweite Lauf schnell und reproduzierbar. Für **erneuten Onlineabruf** der aktuellen BEV-Daten `--refresh` angeben. Mit `--offline` werden ausschließlich bereits vorhandene Cache-Dateien gelesen. Der Testausschnitt ist über die Metadaten der FMZK-Extraktion vorgegeben; es erfolgen keine bundesweiten Massendownloads. Schutzgrenzen: maximal 36 Kacheln und 250 Grundstücksabfragen pro Lauf.

**Achtung zur Vollständigkeit:** Aus Vector Tiles lassen sich keine rechtsverbindlichen vollständigen Grundstücksgrenzen rekonstruieren; sie werden an Tilekanten geschnitten. **Die A/B/C/D-Einstufung beruht ausschließlich auf der vom BEV zurückgegebenen vollständigen Grundstücks-Nutzungsbilanz.** Ohne diese Daten erhält das Grundstück D. Die ausgelieferten GeoJSON-Geometrien sind *Ausschnitte*, keine vollständigen Grundstückspolygone.

Wir prüfen die Ergebnisse zuerst anhand des bekannten Testgebietes und der bereits bewerteten 25 FMZK-Polygone. Erst danach entwickeln wir Regeln, mit denen Verkehrsgrundstücke und Grünflächen tatsächlich flächendeckend zugeordnet werden können.


## Schritt 6: Alle FMZK-Flächen in zwei GeoJSONs aufteilen

Der getrennte Export verwendet **den vollständigen lokalen FMZK-Testausschnitt** (`fmzk_test.gpkg`) und die bereits erzeugten Kataster-Geometrien aus Schritt 5, ohne weitere BEV-API-Abfragen. Der vorherige Katasterlauf ist Voraussetzung, weil der Export ausschließlich die `nfl`-Nutzungsflächen **auf den durch den Kern ermittelten Grundstücksausschnitten** berücksichtigt.


```bash
./scripts/update-and-sync.sh
.venv/bin/python -m scripts.export_fmzk_strassenraum
```

Daraus entstehen unter `data/processed/street_space/`:

- **`fmzk_strassenraum.geojson`**: Alle FMZK-Kernflächen (Klassen 21/23/24/33/39) sowie die weiteren FMZK-Polygone, die zu mindestens **95 % ihrer Fläche** von den Kataster-Nutzungen 95 (Straßenverkehrsanlagen) oder 65 (Verkehrsrandflächen) gedeckt sind und nicht zu mehr als 5 % eine andere Nutzung überlagern.
- **`fmzk_uebrige_flaechen.geojson`**: Alle übrigen FMZK-Polygone. Diese Kategorie bedeutet **nicht** „privat“ oder „kein öffentlicher Straßenraum“. Teilweise überdeckte oder unklare Polygone bleiben hier und erhalten `grund=teilweise_strassenlage_pruefen` bzw. einen Hinweis auf unvollständige Katasterabdeckung.
- **`fmzk_aufteilung_bericht.json`**: Anzahl und Fläche beider Gruppen sowie die Zuweisungsgründe und Kenndaten zur Katastermaske.

**Jedes originale FMZK-Polygon wird vollständig, unverändert im Umriss und genau einmal** in einer der beiden GeoJSON-Dateien ausgegeben. Die originale `fid` und die FMZK-Klasse bleiben erhalten; bei Verfügbarkeit außerdem `FMZK_ID` und einige Quellattribute. Die GeoJSONs haben wie üblich EPSG:4326, Berechnungen erfolgen metrisch in EPSG:31256.

Die überlappenden `nfl`-Vektorkachelfragmente werden vor der Klassifizierung **geometrisch vereinigt**, fehlerhafte Polygonringe repariert. Nicht automatisch übernommene Fälle sind anhand von `kataster_strassenanteil_pct`, `kataster_sonstige_pct` und `kataster_ohne_nutzung_pct` prüfbar. Bei einer Abweichung zwischen FMZK-Kern und Kataster kennzeichnet `pruefhinweis=kern_abweichung_zum_kataster` den Fall, ohne die Kernfläche automatisch zu entfernen.

Die vorsichtige Schwelle von 95 % kann für **Vergleichstests** mit `--min-strassenanteil 0.9` verändert werden. Die Aufteilung bleibt immer eine **vorläufige GIS-Klassifizierung**, weder eine amtliche Abgrenzung noch ein Nachweis der öffentlichen Widmung. Ausschließlich über die Katasterklasse 42 erfasste Parkplätze werden **nicht** automatisch dem Straßenraum zugeordnet (außer ein FMZK-Polygon gehört bereits zum Kern).

Wenn sich die FMZK-Extraktion oder die Kataster-BBOX geändert hat, verweigert der Export die Kombination nicht zusammenpassender Daten. Die Aufteilung verwendet keine historischen `pruefbeispiele`-Bewertungen als automatische Trainingsdaten; diese bleiben unabhängige Kontrollbeispiele.


## Schritt 7: Bodenbegrünungsanteil als unabhängiges Modul bestimmen

Das eigenständige Modul `scripts/measure_ground_greening.py` benötigt **nur** eine Polygon-GeoJSON-Maske des Straßenraums (EPSG:4326) und den FMZK-Testausschnitt. **Es importiert keine Implementierung des Straßenraum-Algorithmus.** Der lokale FMZK-Leser liegt jetzt separat in `scripts/fmzk_source.py` und wird auch von der bisherigen Straßenraumanalyse genutzt.

Es berechnet den **bodenbezogenen** Begrünungsanteil ausschließlich aus `F_KLASSE` **58 und 69** innerhalb der Straßenraum-Maske. Alle Flächen werden zuerst räumlich vereinigt (keine doppelte Zählung überlappender Polygone) und in **EPSG:31256** vermessen. Die Grünflächen werden für die Messung an der Maske geschnitten; die Ermittlung der Straßenmaske selbst bleibt unverändert.

```bash
./scripts/update-and-sync.sh
.venv/bin/python -m scripts.measure_ground_greening
```

Ausgaben unter `data/processed/bodenbegruenung/`:

- `bodenbegruenung_bericht.json`: Straßenraumfläche, tatsächlich zugeordnete Boden-Grünfläche, **Begrünungsanteil in %**, getrennte Werte für FMZK 58/69, methodische Hinweise, Eingabe-Pfade und SHA-256 der Straßenmaske.
- `bodenbegruenung_flaechen.geojson`: an der Maske geschnittene FMZK-Grünteilflächen zum Kontrollieren in der Kartensammlung.

**Erster lokaler Referenzlauf (13.10.2026):** Bei **46.630,56 m²** vorläufigem Straßenraum wurden **889,18 m²** Bodenbegrünung ermittelt, entsprechend **1,91 %**. Grundlage: **487** Straßenraum-Features und **2.401** FMZK-Features; von den **276** FMZK-Grünobjekten überschneiden **107** die Straßenmaske. Die gemessene Begrünung stammt praktisch vollständig aus FMZK-Klasse **69** (889,1828 m²); Klasse **58** trägt nur 0,00165 m² bei. Dies ist ein **vorläufiges Ergebnis für den Testausschnitt**, keine gesicherte Aussage über ganz Wien. Ausführliche Messergebnisse, Masken-SHA-256 und Qualitätsprüfung: [Modulare Architektur – erster Referenzlauf](docs/Modulare-Architektur.md#erster-lokaler-referenzlauf--bodenbegrünung-13102026).

**Austauschbar:** Ein späteres Straßenraumverfahren muss nur eine geometrisch gültige Polygon-`FeatureCollection` in EPSG:4326 für denselben Testbereich erzeugen. Attribute aus FMZK oder Kataster sind für das Begrünungsmodul nicht erforderlich.

```bash
.venv/bin/python -m scripts.measure_ground_greening \
	--street-geojson data/processed/alternative/strassenraum.geojson
```

Der Anteil ist **noch keine endgültige Qualitäts- oder Gartenstraßenbewertung**: Unklare Straßenraumflächen außerhalb der jetzigen Maske fehlen im Zähler und im Nenner. Kronenüberschirmung wird später in einem eigenen Modul berechnet und **nicht** mit Bodenbegrünung vermischt. Details und feste Modulschnittstelle: [Modulare Architektur](docs/Modulare-Architektur.md).

## Schritt 8: Modul 4 – Baumkronen und Überschirmung vergleichen

**Modul 4 besitzt separate Kronen-Erzeuger und eine davon unabhängige Messfunktion.** Es verwendet dieselbe austauschbare Straßenraum-Maske wie Modul 3. Bäume, deren Stamm außerhalb des Straßenraums steht, können dennoch eine Überschirmungsfläche beitragen.

Erste Methode **A (Wiener Baumkataster/WFS)**, vorerst nur für das vorhandene kleine Testgebiet:

```bash
./scripts/update-and-sync.sh
.venv/bin/python -m scripts.fetch_vienna_trees  # nur nötig, wenn WFS-Cache fehlt
.venv/bin/python -m scripts.build_canopy_circles --wien data/processed/baumkronen/baumkataster_wfs.geojson
.venv/bin/python -m scripts.measure_canopy_cover
```

Lokale Ergebnisse:

- `data/processed/baumkronen/baumkataster_wfs.geojson`: vom WFS geladene Baum-Punkte, mit Bericht und geprüftem BBOX-Ausschnitt.
- `data/processed/baumkronen/baumkronen_kreise.geojson`: Kreise aus Stammposition und halbem Kronendurchmesser mit dokumentierten Auslassungen.
- `data/processed/ueberschirmung/ueberschirmung_bericht.json`: Straßenraum, tatsächlich überschnittene Kronenfläche, Überschirmungsgrad und Eingabeversionen.
- `data/processed/ueberschirmung/ueberschirmte_flaeche.geojson`: die vereinigten Baumkronen **innerhalb** des Straßenraums, zur Kartenkontrolle.

**Erster lokaler WFS-Abruf erfolgreich (13.10.2026): 252 Baumstandorte.** Nach dem behobenen WFS-`crs`-Problem wurde ein erster Messlauf durchgeführt (117 Kreise, 536,88 m², **1,15 %**). **Dieser Wert ist ungültig und verworfen**, weil `KRONENDURCHMESSER` als Meter statt als **Kategoriencode** behandelt wurde. Korrekt steht die metrische Klasse in `KRONENDURCHMESSER_TXT` (z. B. `16-18 m`). Der überarbeitete Kronenprovider verwendet nun für **geschlossene Klassenintervalle** den **Mittelwert** (17 m im Beispiel); unbekannte/offene Bereiche werden mit Ausschlussgrund dokumentiert und nicht frei geschätzt. **Nur Kronenkreise und Überschirmungsmessung erneut berechnen**, kein neuer WFS-Download notwendig. **Der neue lokale Lauf ergab vorläufig 117 Kronenkreise, 3.647,05 m² Kronenüberschirmung und 7,82 % auf 46.630,56 m² Straßenraum.** Der nachgereichte Bericht erklärt die Auswahl nun vollständig: **252 WFS-Punkte − 20 unbekannte Kronenklassen − 1 offene Klasse (`>21 m`) = 231 verwertbare Bäume; davon 57 außerhalb des Untersuchungsbereichs und 57 Kreise ohne Kontakt zum Testausschnitt → 117 erzeugte Kreise.** Die Zahlen sind damit konsistent. Noch offen bleibt, ob die 21 unbestimmten Kronenklassen die Straßenraumüberschirmung beeinflussen würden und wie gut die Kreisnäherung mit Orthofotos übereinstimmt. **7,82 % bleibt daher ein vorläufiger Messwert**, keine validierte Genauigkeitsangabe.

### Methode B – Wien + OpenStreetMap als eigenständiger Kronenprovider

Die bisherige OSM-Option im A-Skript wurde entfernt: **A ist ausschließlich Wiener Baumkataster**, B hat einen **eigenen** OSM-Download, Merge und Ausgabeordner. Gemeinsam genutzt wird nur `scripts/canopy_tree_common.py` für die unveränderten Wiener Klassenmittelwerte und metrischen Kreise. Die eigentliche Quellenkombination stammt aus dem bestehenden [Baumkataster-Build der Kartensammlung](https://github.com/peter-alexander/kartensammlung-overlay-builds/blob/main/baumkataster/build.mjs) und ist als `scripts/canopy_osm_merge.py` umgesetzt: **Wien vor OSM-Einzelbäumen vor Baumreihen**, 4 m gegen Wien, 0,75 m zwischen OSM-Nodes, 4/3 m für Baumreihendubletten, Baumreihen mit `tree_count` oder ungefähr **8 m** Abstand.

```bash
# A wurde bereits lokal berechnet; nur B muss neu laufen
./scripts/update-and-sync.sh

# Overpass für den gepufferten kleinen Testausschnitt
.venv/bin/python -m scripts.fetch_osm_trees

# OSM zu Wien ergänzen, mit gekennzeichneten Kronenschätzungen
.venv/bin/python -m scripts.build_canopy_combined

# Keine Änderung am gemeinsamen Überschirmungsmessmodul
.venv/bin/python -m scripts.measure_canopy_cover \
	--crowns-geojson data/processed/baumkronen/variante_b/baumkronen_kombiniert.geojson \
	--out-dir data/processed/ueberschirmung/variante_b

# A, B und C auf genau demselben Straßenraum vergleichen
.venv/bin/python -m scripts.compare_canopy_methods \
	--candidate baumkataster=data/processed/baumkronen/baumkronen_kreise.geojson \
	--candidate kombiniert=data/processed/baumkronen/variante_b/baumkronen_kombiniert.geojson \
	--candidate grm2023=data/processed/baumkronen/grm2023/processed/baumkronen_grm2023.geojson
```

Die OSM-Einzelbäume haben oft **keinen** gemessenen Kronendurchmesser. B verwendet dafür **ausdrücklich gekennzeichnet** dieselbe *Höhe×0,5*-Näherung wie die bisherige 3D-Schattenberechnung (fehlende OSM-Höhe: angenommene 12 m → 6 m Krone). Die Option `--strict-osm` erzeugt eine Untervariante ohne solche Schätzungen. **Diese Angaben sind keine vermessenen Kronen.** Wien erhält keine neuen Schätzungen, sodass seine Teilmenge in A und B identisch bleibt.

Ergebnisse unter `data/processed/baumkronen/variante_b/` (`baumkronen_kombiniert.geojson`, `baumkronen_kombiniert_bericht.json`), Messbericht unter `data/processed/ueberschirmung/variante_b/`. **Der erste echte B-Lauf wurde lokal erfolgreich durchgeführt:** 140 OSM-Einzelbäume, davon 128 bereits innerhalb von 4 m eines Wiener Baumstandorts; 12 OSM-Ergänzungen nach Dublettenprüfung, vier davon mit Kronenkontakt zum Testgebiet (drei explizite Kronendurchmesser, eine gekennzeichnete Schätzung). Es gab **keine OSM-Baumreihen** im Ausschnitt. B ergibt **3.678,65 m² / 7,89 %**, also nur **+31,60 m² bzw. +0,068 Prozentpunkte** gegenüber A (3.647,05 m² / 7,82 %). C bleibt bei **4.358,69 m² / 9,35 %**; IoU **A/B 99,14 %, A/C 58,02 %, B/C 57,67 %**. Die echten Baumreihen und das Verhalten ohne Schätzungen sind gesondert zu prüfen. Die gemeinsame Straßenraumfläche beträgt 46.630,56 m². Eine eigene BEV-Infrarot-Auswertung ist weiterhin eine spätere Option.

**[Ausführliche Anleitung, Datenquellen und Grenzen von Modul 4](docs/Modul-4-Baumkronen-Vergleich.md).** Die Bodenbegrünung von **1,91 %** bleibt eine eigenständige Kennzahl und darf nicht zur Überschirmung addiert werden.


### Variante C: Grünraummonitoring 2023 – bestätigte WMS-Baumschicht

Das **Grünraummonitoring 2023** (`GRM2023OGD`) enthält eine ausdrücklich klassifizierte **Baumschicht (Fachklasse 3)**. **Erhebungsjahr dieser Daten ist 2023, nicht 2022:** amtlich genannte Sommerbefliegungen **14./18. Juli und 21./22. August 2023**. Das eigenständige `GRM2022OGD` basiert dagegen auf Aufnahmen von 2022; die Unterscheidung ist für vermeintlich neu gepflanzte Bäume im aktuellen Kataster wichtig. [Datensatz-Metadaten 2023](https://www.data.gv.at/datasets/ec7be5af-5b15-302a-9757-fb2a45181c8a?locale=de). Der WMS lieferte im lokalen Testbild **923 × 858 Pixel**, exakt **neun opake RGB-Klassenfarben ohne Antialiasing-Mischpixel**. Durch Abgleich mit der gelieferten Legende wurde `#38A800` eindeutig als **Baumschicht** identifiziert; die **71.892 Baumschicht-Pixel** belegen im gesamten angefragten WMS-Bild rund **17.958 m²**. **Das ist nicht die Straßenraum-Überschirmung.** Das Anfragegitter ist ungefähr 0,5 m groß; es ist noch kein geprüfter nativer Rohdatenexport.

Das separate Modul `scripts/build_canopy_grm2023.py` erzeugt daraus eine **metrisch korrekt georeferenzierte Polygonmaske**. Unbekannte Farben, widersprüchliche Quelldaten-Hashes, Projektionen oder World-Dateien führen zu einem Abbruch.

Die WMS-Diagnose ist bereits lokal erfolgt; sie muss für denselben Bildstand **nicht wiederholt werden**. Als nächstes:

```bash
./scripts/update-and-sync.sh

# Polygonmaske der Baumschicht erzeugen
.venv/bin/python -m scripts.build_canopy_grm2023

# Dieselbe Überschirmungsberechnung wie bei den Wiener Baumkataster-Kreisen
.venv/bin/python -m scripts.measure_canopy_cover \
	--crowns-geojson data/processed/baumkronen/grm2023/processed/baumkronen_grm2023.geojson \
	--out-dir data/processed/ueberschirmung/grm2023

# Räumlich vergleichen: Kronenkreise (A) gegen WMS-Baumschicht (C)
.venv/bin/python -m scripts.compare_canopy_methods \
	--candidate baumkataster=data/processed/baumkronen/baumkronen_kreise.geojson \
	--candidate grm2023=data/processed/baumkronen/grm2023/processed/baumkronen_grm2023.geojson
```

**Diese drei lokalen Schritte wurden erfolgreich ausgeführt.** Ergebnisse: `data/processed/baumkronen/grm2023/processed/baumkronen_grm2023.geojson` und `baumkronen_grm2023_bericht.json`, `data/processed/ueberschirmung/grm2023/ueberschirmung_bericht.json` und der Methodenvergleich unter `data/processed/ueberschirmung/vergleich/`. Die Berichte wurden geprüft und die Kennzahlen in der [Modul-4-Dokumentation](docs/Modul-4-Baumkronen-Vergleich.md) gesichert.

**Gemessener Referenzvergleich, Testausschnitt 13.–14.10.2026:**

| Überschirmung | A: Baumkataster-Kreise | C: GRM2023-Baumschicht |
| --- | ---: | ---: |
| Straßenraumfläche | 46.630,56 m² | 46.630,56 m² |
| Kronenfläche über Straße | 3.647,05 m² | 4.358,69 m² |
| **Überschirmungsgrad** | **7,82 %** | **9,35 %** |

**Räumliche IoU: 58,02 %**; gemeinsame Kronenfläche **2.939,61 m²**, nur A **707,44 m²**, nur C **1.419,08 m²**. Der Rasterprovider hat **71.892 Baum-Pixel** in **1.298 Polygon-Teilstücke** übertragen; berechnete Pixel- und Polygonfläche entsprechen sich praktisch exakt (**17.958,20 m² im gesamten WMS-Ausschnitt**, nicht nur über Straßenraum). **Das belegt die technische Übertragung, nicht die externe Genauigkeit der Kronenklassifikation.** Jetzt gilt es, die Unterschiede geographisch sichtbar zu machen und anhand Orthofoto/Referenzflächen zu prüfen. Keine der Methoden wird allein wegen der größeren Fläche als besser bewertet.

**Modul 4 bleibt unverändert austauschbar:** WMS-Klassifizierung und Kronenkreise liefern beide `Polygon`/`MultiPolygon`-GeoJSON in EPSG:4326; der Prozentwert entsteht erst beim Schnitt mit der identischen Straßenraum-Maske. Ein WMS-GetMap-Raster ist ein Renderergebnis, kein Beleg dafür, dass alle Zellgrenzen exakt dem 50-cm-Originalraster entsprechen.

Die Details, geprüfte Farbtabelle und Qualitätsgrenzen sind in [Modul 4 – Baumkronen-Vergleich](docs/Modul-4-Baumkronen-Vergleich.md) dokumentiert.

### Methode D – Vorrangig vorhandener BEV-WMS aus der Kartensammlung

In [`Kartensammlung/src/app/basemaps/providers/imagery.js`](https://github.com/peter-alexander/Kartensammlung/blob/main/src/app/basemaps/providers/imagery.js) werden bereits **fünf BEV-Orthofoto-Darstellungen** über `https://kataster.bev.gv.at/ortho/ows` verwendet: `bev:RGB`, `bev:IRGB`, `bev:RGIR`, `bev:RIRB` und `bev:IR`. Damit können wir **ohne vorzeitigen Download riesiger 50-km-RGBI-Kacheln** einen ersten Versuch beginnen.

**Erster Schritt: WMS-Kanäle auf demselben Rastergitter vergleichen.** Dafür existiert der eigenständige Adapter `scripts/probe_bev_wms.py`. **BEV-Besonderheit aus dem ersten lokalen Versuch:** Die vier Infrarot-/Falschfarben-Layer werden nicht in `GetCapabilities` aufgelistet, funktionieren aber laut Kartensammlung direkt per `GetMap`. Die fehlende Auflistung wird daher nur im Diagnosebericht dokumentiert, nicht mehr als Fehler gewertet. Erst die tatsächlichen fünf gültigen PNG-Antworten entscheiden über die Nutzbarkeit:

```bash
./scripts/update-and-sync.sh
.venv/bin/python -m scripts.probe_bev_wms
```

Er fordert **einen** gepufferten Testausschnitt im selben WMS-Pixelgitter (EPSG:3857) in allen fünf Darstellungen an, speichert die fünf `PNG/PGW/PRJ`-Tripel lokal unter `data/processed/baumkronen/bev_wms/` und erstellt **`bev_wms_diagnose.json`** mit den Bildgrößen, Anfrage-/Dateiprüfsummen und dem pixelweisen Vergleich der Rot-, Grün-, Blau- und NIR-Kanäle. **Kein NDVI, keine Kronenmaske, keine Überschirmungsmessung**: Die WMS-Werte sind Darstellungswerte, keine kalibrierten Reflexionsdaten. **Der erste echte Abruf ist erfolgt:** 943×878 Rasterpixel, alle fünf PNGs gültig, 827.954 gemeinsame Pixel. **Neun von elf Kanalvergleichen sind pixelgenau zu 100 % identisch.** Lediglich die Rot-/Grün-Darstellungen in `bev:IRGB` weichen stark ab (20,58 % bzw. 14,86 % innerhalb ±1 DN). RGB aus `bev:RGB` und NIR aus `bev:IR` sind über die anderen Ebenen intern bestätigt. Der Bericht hat nun getrennte Flags für den **Kernkanalvergleich** und für **alle Darstellungen**; `IRGB`-Abweichungen werden weiterhin ausgewiesen. Der nächste mögliche Schritt ist **ein experimenteller, nicht kalibrierter WMS-Vegetationsindikator** aus lokal gespeicherten RGB-/IR-Bildern, vor einer Baumkronenklassifikation.

### D2: Vegetationserkennung ohne Höhenmodell – lokaler Versuch

**Implementiert:** `scripts/analyze_bev_vegetation.py` arbeitet ohne erneute BEV-WMS-Abfrage mit den bereits gespeicherten Bildern `bev_rgb_test.png` und `bev_ir_test.png`. Rot (`bev:RGB.R`) und NIR (`bev:IR.R`) wurden bereits über unabhängige WMS-Darstellungen als intern konsistent geprüft. Das Skript akzeptiert auch den **vorliegenden älteren Diagnosebericht** ohne das später ergänzte Kernkanal-Statusfeld, sofern sämtliche relevanten Einzelvergleiche erfolgreich waren. Es prüft Bilddateien, SHA-256 und Georeferenzierung und ändert die Originalbilder nicht.

```bash
./scripts/update-and-sync.sh
.venv/bin/python -m scripts.analyze_bev_vegetation
```

**Ergebnisse:** `data/processed/baumkronen/bev_vegetation/bev_vegetation_vergleich.png` zeigt RGB, IR, kontinuierlichen Index und vier explorative Vegetationsüberlagerungen (`0,10`, `0,20`, `0,30`, `0,40`). Dazu kommen `bev_vegetation_bericht.json` mit den gültigen/ungültigen Pixeln und Trefferanteilen sowie **einzeln georeferenzierte PNG/PGW/PRJ** für Index, Masken und Überlagerungen. **Das Vergleichsblatt selbst ist kein georeferenziertes Einzelraster.** Für weitere Varianten können `--thresholds 0.05,0.15,0.25,0.35 --out-dir data/processed/baumkronen/bev_vegetation_versuch2` verwendet werden.

**Wichtige Grenze:** `(NIR - R) / (NIR + R)` arbeitet hier mit *gerenderten 8-bit-WMS-Anzeigewerten*. Es ist ein **unkalibrierter WMS-Vegetationsindex**, kein geprüfter NDVI. Erkannte Kandidaten können Bäume, Wiesen, Beete oder Sträucher sein. Die dargestellten Prozentanteile beziehen sich nur auf die Pixel des **gesamten WMS-Bildausschnitts**, nicht auf den Straßenraum. Es werden **keine Baumkronenpolygone** und **keine Überschirmungsgrade** erzeugt. Erst anhand des Vergleichsbilds entscheiden wir, ob und wie sich die Vegetation zuverlässig trennen lässt. **Der erste lokale D2-Test ist nun ausgewertet:** 827.954 gültige Pixel, Kandidatenanteile über den gesamten WMS-Ausschnitt von **15,14 %** (Schwelle 0,10), **12,14 %** (0,20), **8,90 %** (0,30) und **4,58 %** (0,40). Visuell liefern 0,20/0,30 brauchbare Kandidaten für Baumreihen; 0,40 verliert viele schwächere und verschattete Teile, 0,10 zeigt mehr unsichere Kleinflächen. Große zusammenhängende Innenhofvegetation enthält weiterhin potenziell Bäume **und** bodennahe Vegetation. Diese Bildanteile sind **keine Straßenraumüberschirmung**. Als nächstes müssen kleine Referenzflächen nach Bäumen, Rasen/Beeten, Sträuchern und Schatten ausgewertet werden, bevor D als Baumkronen-Methode gilt.

[Ausführliche Methodik D2, Dateiformate und Validierung](docs/Modul-4-Baumkronen-Vergleich.md#d2--experimentelle-vegetationserkennung-ohne-dsmdtm-14102026-implementiert).

### D3: 0,10-Vegetationsmaske + 0,20-Signalstärke zur Kronenkandidatenprüfung

**Implementiert als separater Versuch**, ohne Höhenmodell und ohne Änderung an A/B/C oder D2: `scripts/segment_bev_vegetation.py`. Jede zusammenhängende 0,10-Vegetationsregion wird geprüft, ob sie einen 0,20-Kern enthält (*Hysterese*). Zusätzlich werden Größe, Form sowie die **RGB-Textur zwischen benachbarten Pixeln innerhalb der Vegetationsfläche** ausgewertet. Daraus entstehen **nur unvalidierte Kronenkandidaten** und getrennte Kategorien für strukturarme, kleine, unklare oder kernlose Vegetationsflächen.

```bash
./scripts/update-and-sync.sh
.venv/bin/python -m scripts.segment_bev_vegetation
```

Ergebnisse unter `data/processed/baumkronen/bev_segmentierung/`:

- `bev_segmentation_kandidaten.png`: Orthofoto mit grün markierten strukturreichen Kronenkandidaten, blau markierter strukturarmer Vegetation, gelben unklaren und grauen kernlosen Bereichen.
- `bev_segmentation_klassen.png`: transparente Klassenvisualisierung ohne Orthofoto.
- `bev_segmentation_hysterese.png`: reine Maske aller Regionen, die wenigstens einen 0,20-Pixel enthalten.
- `bev_segmentation_kronenkandidaten.png`: **nur** die RGB-texturreichen Kandidaten als Prüfraster, **kein** bestätigtes Kronenpolygon.
- `bev_segmentation_bericht.json` und `bev_segmentation_objekte.json`: Mengenbilanz sowie Größe, Form, Textur und Kernanteil jedes Objekts.

**Erster realer D3-Lauf (14.10.2026) ausgewertet:** Von **125.345** Vegetations-Kandidatenpixeln werden **104.483 (83,36 %)** als *strukturreiche Kronenkandidaten* eingefärbt, **17.894 (14,28 %)** als unklar, **2.046 (1,63 %)** als kernlos. Es gibt **966** zusammenhängende Regionen; die Hysterese behält **98,37 %** der 0,10-Maske. Im Bild erscheinen jedoch mehrere **wahrscheinliche Straßenbaumreihen gelb/unklar**, während ein großer **gemischter Innenhof fast vollständig grün** erscheint. Fazit: **0,10 als Vegetationsmaske bestätigen, Texturregel nicht als Kronenerkennung akzeptieren.** Die Formwerte werden derzeit nur ausgegeben, noch nicht zur Klassifikation verwendet. Eine unabhängige Prüfung an markierten Baum-/Rasen-/Strauchregionen und an lokalen Texturfenstern ist der nächste Schritt; weiterhin kein Überschirmungsgrad.

Alle vier PNGs erhalten eigene `PGW/PRJ`-Georeferenzierung (EPSG:3857). Die Texturschwellen sind bewusst **noch nicht kalibriert** (zunächst 8 DN als strukturreich, 4 DN als strukturarm). Kronen können homogen und Rasenflächen strukturiert sein, außerdem können Baumkronen an Vegetationsflächen angrenzen. Deshalb **keine Kronenquote und kein Überschirmungsgrad**; zunächst die Bildklassifikation überprüfen. Die 0,10-Maske bleibt auch dort als ursprüngliche, großzügige Vegetationsdetektion erhalten, wo ein Objekt mangels 0,20-Kern nicht in die Hysterese-Maske aufgenommen wurde.

[Modul-4-Dokumentation einschließlich des lokalen Schwellen-Feinvergleichs und der Grenzen von D3](docs/Modul-4-Baumkronen-Vergleich.md#d2-feinvergleich-und-d3-vorsichtige-kronenkandidaten-ohne-höhenmodelle-14102026).

### D-Variantenvergleich auf dem Straßenraum – alle bisherigen Schwellen und D3-Klassen

**Bevor weitere Kronenregeln entwickelt werden, messen wir zunächst die vorhandenen D-Masken.** `scripts/compare_bev_variants.py` berechnet **für dieselbe Straßenraummaske wie A/B/C** den metrischen Flächenanteil von sieben D2-Schwellen (`0,10`, `0,15`, `0,17`, `0,18`, `0,20`, `0,30`, `0,40`) und den D3-Varianten: Hysterese, nur strukturreiche Kronenkandidaten, Kronenkandidaten plus unklare Vegetation sowie sämtliche D3-Einzelklassen.

```bash
./scripts/update-and-sync.sh
.venv/bin/python -m scripts.compare_bev_variants
```

**Es wird nichts neu heruntergeladen oder verändert.** Der Vergleich reproduziert D2/D3 aus den ursprünglichen SHA-geprüften RGB-/IR-Bildern, nutzt die vorhandene Straßenraum- und FMZK-Maske und vergleicht optional die Kronenflächen A/B/C, wenn deren GeoJSONs vorhanden sind. Positive Rasterzellen werden als georeferenzierte Flächen polygonisiert und **an der Straßenraumgrenze geometrisch angeschnitten** – inklusive anteiliger Randzellen, statt die Bildanteile als Straßenanteile auszugeben.

Die Konsole zeigt für alle Varianten Fläche **in m² und Prozent**. Der Bericht liegt unter `data/processed/baumkronen/bev_variantenvergleich/bev_varianten_strassenraum_vergleich.json`. **Unbedingt unterscheiden:** D2 liefert Vegetationsbedeckung und D3 liefert unvalidierte Kronenkandidaten; noch kein D-Wert ist ein nachgewiesener Wien-Plan-Überschirmungsgrad. Zuerst die echten Quoten vergleichen, **dann** über die nächste Segmentierung entscheiden. [Methodische Details](docs/Modul-4-Baumkronen-Vergleich.md#zwischenmessung-d2d3-alle-d-varianten-auf-identischem-straßenraum-14102026).

**Festgelegter Zwischenstand Methode D (14.10.2026):** Die D2-Schwelle **0,20 ist die Baseline** für künftige Vergleiche. D erkennt damit experimentell Vegetationsflächen im Straßenraum; **eine verlässliche Unterscheidung zwischen Baumkronen und sonstiger Vegetation (z. B. Rasen, Beeten, Sträuchern) ist noch nicht umgesetzt**. D3-Kronenkandidaten sind dafür nicht ausreichend validiert. Die Baumkronentrennung bleibt ein **offener Punkt**. Wir lassen D vorerst unverändert und führen keine weitere Schwellenoptimierung oder Klassifikationsentwicklung durch. Die D-Vegetationsbedeckung ist **kein Baumkronen-Überschirmungsgrad**.

**Die TIFF-/RGBI-Diagnose bleibt als Fallback**, falls die Kanäle des gerenderten BEV-WMS nicht geeignet sind. Sie ist im folgenden Abschnitt beschrieben.

### Optionale Originaldaten: BEV Orthofoto RGBI – Rasterdiagnose

**Stand 14.10.2026:** Der BEV bietet echte digitale RGBI-Orthofotos mit etwa **20 cm** Bodenauflösung an. **RGBI** enthält den Nahinfrarotkanal zusätzlich zu RGB. [Offizielle BEV-Produktbeschreibung](https://www.bev.gv.at/Services/Produkte/Luftbildprodukte/Orthophoto-Farbe.html). Die frei verfügbaren [BEV-Daten](https://data.bev.gv.at/) werden unter anderem als **50 × 50-km-Kacheln** abgegeben; bitte vor dem Download Dateigröße, Gebietsabdeckung und tatsächliches Flugjahr kontrollieren. Einige [BEV-RGBI-Datensätze](https://data.europa.eu/data/datasets/34490301-7c3e-40b4-8cb8-e82e5c304e8e~~1) enthalten **separate RGB- und NIR-TIFFs**.

Mit `scripts/probe_bev_rgbir.py` haben wir eine **eigenständige D1-Diagnose** vorbereitet (GDAL erforderlich, `sudo apt install gdal-bin`). Sie prüft Projektion, Bandzahl/Interpretation und Georeferenzierung. Ein Zuschnitt ist optional; **es werden noch keine Baumkronen klassifiziert**.

```bash
./scripts/update-and-sync.sh

# Entweder: ein echtes RGBI-TIFF mit vier Bändern
.venv/bin/python -m scripts.probe_bev_rgbir --input /pfad/bev_rgbi.tif

# Oder: separate BEV-RGB- und -NIR-Dateien
.venv/bin/python -m scripts.probe_bev_rgbir \
	--input /pfad/bev_rgb.tif \
	--nir-input /pfad/bev_nir.tif

# Wenn der Metadatencheck passt: oben gewählten Aufruf um --clip ergänzen.
```

Die Auswertung schreibt `data/processed/baumkronen/bev_rgbir/bev_rgbir_diagnose.json`; mit `--clip` zusätzlich einen kleinen EPSG:31256-TIFF-Ausschnitt (bei getrennten Quellen zwei ausgerichtete Testdateien). **A/B/C bleiben unverändert.** Ein NDVI darf erst entstehen, nachdem die tatsächliche Zuordnung von Rot und NIR und das Datenjahr überprüft wurden. Auch dann erkennt NDVI **Vegetation und nicht automatisch Baumkronen**; eine fachliche Kronenabgrenzung mit Form-/Höhenprüfung ist ein separater nächster Schritt.

[Quellen, Bezugsmöglichkeiten, Risiken und die Schritte D1–D4](docs/Modul-4-Baumkronen-Vergleich.md#variante-d-bev-orthofoto-rgbi--quellenprüfung-d1-14102026).

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

## Nächste Schritte (modular)

1. **Modul 5 – Straßenabschnitte als Bezugsräume vorbereiten:** Der erste reale lokale GIP-Abruf ist ausgewertet: **80 Straßenachsen und 47 Knoten**, keine doppelten IDs. Alle 140 Linienenden mit abrufbarem Knoten stimmen lagegenau überein; die 20 restlichen Endpunkte liegen außerhalb der angefragten WFS-BBOX. Vier Teilnetze (74/3/2/1 Achsen) erfordern eine differenzierte Behandlung. Der Topologieprüfer `scripts/analyze_gip_topology.py` und ein **experimenteller Flächenpartitionierer** `scripts/assign_gip_section_areas.py` sind vorhanden. Die erste geometrische Aufteilung wird lokal aus vorhandener Straßenmaske und GIP-Daten erzeugt, Kreuzungen/Sonderwege/Reste bleiben explizit ungeklärt. Der erste reale Durchlauf liefert **43.217,91 m² (92,68 %) auf 45
Abschnitte zugeordnet und 3.412,65 m² (7,32 %) ungeklärt**, davon
3.368,09 m² Kreuzungszonen. Die Flächenbilanz hat keine messbaren
Lücken oder Überlappungen; die räumliche Zuordnung ist jedoch
**noch nicht visuell/fachlich validiert**. Als Nächstes die beiden
Ausgabe-GeoJSONs prüfen, **ohne** bereits Quoten je Abschnitt
als gesicherte Kennzahlen auszugeben. **Ausführung und Prüfkriterien:** [Modul 5 – Straßenabschnitte](docs/Modul-5-Strassenabschnitte.md). Noch keine mit realer Straßenmaske validierten Abschnittspolygone erzeugt.
2. **Bodenbegrünung und Baumkronenüberschirmung je Abschnitt messen**, nachdem die Geometriebilanz überprüft wurde. Die bestehenden Gesamtwerte A/B/C und Bodenbegrünung nicht verändern und Quoten nicht addieren.
3. **Methode D als abgeschlossenes Zwischenergebnis belassen:** D2 **0,20 als Baseline** für Vegetation. Die **Trennung von Baumkronen und sonstiger Vegetation bleibt offen**; derzeit keine weitere D-Optimierung.
4. **Später fachlich prüfen:** FMZK-Klasse 58 in Modul 3, unsichere Randbereiche und mögliche Fehlzuordnungen von Modul 2. Die Module nur auf Grundlage konkreter Prüffälle verändern.

Die vollständige Beschreibung der derzeitigen Zuordnungsregeln und Grenzen steht in [docs/Methodik-Strassenraum-FMZK-Kataster.md](docs/Methodik-Strassenraum-FMZK-Kataster.md).

Datenquelle: **Stadt Wien – data.wien.gv.at**, gemäß [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.de). 
