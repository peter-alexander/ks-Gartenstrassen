# Modul 4: Baumkronen und Überschirmungsgrad – modulare Vergleichsstrecke

**Stand:** 14. Oktober 2026. **Status:** Die unabhängigen Kronenprovider **A (Wiener Baumkataster) und C (Grünraummonitoring 2023)** wurden im selben Straßenraum lokal ausgeführt und die Flächenwerte dokumentiert: **7,82 % bzw. 9,35 %**, räumliche IoU **58,02 %**. Der WMS-Kronenexport stimmt flächenmäßig mit den 71.892 klassifizierten Pixeln überein. **Die fachliche Genauigkeit der beiden Verfahren ist noch nicht anhand unabhängiger Referenzflächen validiert.** Die Straßenraum-Abgrenzung aus Modul 2 und die Bodenbegrünung aus Modul 3 bleiben unverändert.

## Feste Schnittstellen

Modul 4 besteht aus voneinander unabhängigen Schritten:

1. **Quelladapter** beschaffen Daten und legen sie lokal unter `data/` ab.
2. **Kronen-Provider** erzeugen jeweils eine **GeoJSON-FeatureCollection aus Polygon/MultiPolygon in EPSG:4326**. Alle Quellenattribute dürfen unterschiedlich sein; nur die Geometrie ist verpflichtend.
3. **Überschirmungsmessung** erhält beliebige Kronen-Polygone plus das **Straßenraum-Polygon-GeoJSON** von Modul 2. Sie rechnet metrisch in EPSG:31256: `100 × Fläche(Vereinigung(Kronen) ∩ Vereinigung(Straßenraum)) / Fläche(Vereinigung(Straßenraum))`.
4. **Vergleichsmodul** berechnet pro Kronenquelle dieselbe Quote und zusätzlich paarweise **Kronenflächen-Überlappung (IoU)** und nur in einer Quelle vorhandene Flächen. **Eine hohe IoU ist keine gemessene Genauigkeit**, sondern nur eine Ähnlichkeit zweier Verfahren.

Kronen dürfen über Straßenflächen ragen, obwohl der Baumstamm **außerhalb** liegt. Überlappende Kronen werden in der Flächensumme nur **einmal** gezählt. Überschirmung wird **nicht zur Bodenbegrünung addiert**; die Ebenen können übereinander liegen.

## Vier zu prüfende Kronenquellen

| Ansatz | Datengrundlage | Geometriemodell / Aussage | Stand |
| --- | --- | --- | --- |
| **A – Wien Baumkataster** | Punkte via WFS `ogdwien:BAUMKATOGD`; metrische **Klasse als Text in `KRONENDURCHMESSER_TXT`**; `KRONENDURCHMESSER` ist **nur der Kategoriencode** | Kreis um Stammpunkt; Radius = halber **Intervallmittelwert** (z. B. `16-18 m` → 17 m Durchmesser → 8,5 m Radius); Näherung | **Erster korrigierter lokaler Lauf: 7,82 %; visuelle Genauigkeitsprüfung ausständig** |
| **B – Wien + OpenStreetMap** | Gleiche Baumkatasterdaten, dazu OSM `natural=tree` mit `diameter_crown` oder `crown_diameter` | Fehlende Bäume ergänzen, mögliche Dubletten behandeln; fehlende Durchmesser ausdrücklich markieren oder nur mit Opt-in schätzen | **Vorbereitet/implementiert** |
| **C – Grünraummonitoring 2023** | Stadt-Wien-Rasterklassifikation; **50 cm Quellauflösung**, **Baumschicht als Klasse 3**, Sommerbefliegungen 2023 | Unabhängige Kronengeometrie aus geprüftem WMS-GetMap-Farbraster; im Testbild **#38A800** = Baumschicht, 71.892 Pixel; Rasterzellen als Polygone | **Lokaler Raster-/Polygonlauf geprüft, Straßenraumquote 9,35 %; visuelle Genauigkeitsprüfung ausständig** |
| **D – BEV Orthofotos mit Infrarot** | BEV RGB/NIR bzw. IR-Darstellungen | Eigene Kronensegmentierung; nur NIR/NDVI allein trennt Bäume nicht sicher von Gras/Sträuchern, Höhe/Objektgrenzen benötigt | **Recherche, keine Implementierung** |

**Hinweis zu C:** Die Wiener OGD-Metadaten führen sowohl **Grünraummonitoring 2022** als auch **2023**; die 2023er Daten sind tatsächlich veröffentlicht. Die abgerufene WMS-Darstellung ist **kein garantierter kategorischer GeoTIFF-Rohdatenexport**. Vor der Automatisierung müssen wir die konkrete GetCapabilities-Ebene, den tatsächlich vorliegenden WMS-Rastertyp, NoData/Transparenz sowie die eindeutige Zuordnung zur **Baumschicht (3)** prüfen. Aus einer hübschen WMS-Kartenfarbe allein darf noch kein Kronenflächenwert abgeleitet werden.

**Hinweis zu B / Kartensammlung:** Der MapLibre/Maptoolkit-Code unter `Kartensammlung/src/app/overlays/providers/stadtplan-wien.js` verwendet `https://tiles.radlobby.at/Baumkataster/tilejson.json` mit `sourceLayer=baumkataster` und erkennt `KS_SOURCE=osm_tree` bzw. `osm_tree_row`. Die dort benutzten **Zoom-Pixelradien** sind für Kartenvisualisierung, **nicht** die metrischen Kronenradien der Messung. Die Herkunft des OSM-/Baumreihen-Imports ist im verlinkten Overlaycode sichtbar, die ursprüngliche Erzeugung des Tile-Datensatzes wurde nicht unabhängig geprüft.

## Jetzt implementierte Scripts

| Skript | Eigenständige Rolle |
| --- | --- |
| `scripts/fetch_vienna_trees.py` | Kleiner WFS-Abruf des Wiener Baumkatasters für die FMZK-Test-BBOX **plus 35 m Rand**; Cache und GeoJSON-Validierung, Schutz gegen maxFeatures-Abschneiden |
| `scripts/build_canopy_circles.py` | Kronenkreise aus **separaten lokalen GeoJSON**-Eingaben Wien/OSM; eigene Qualitäts- und Dublettenberichte |
| `scripts/measure_canopy_cover.py` | Universelle Kronen-Flächenmessung, **unabhängig vom Kronen-Provider**, identischer Straßenraumvertrag wie Modul 3 |
| `scripts/compare_canopy_methods.py` | Vergleicht 2+ Kronen-GeoJSONs auf identischem Straßenraum: Prozentsatz, IoU, Fläche nur A/nur B |

**Erster echter lokaler WFS-Abruf bestätigt (13.10.2026):** Der Wiener WFS hat **252 Baum-Punkte** geliefert (`wfs_heruntergeladen`) und die bestehende BBOX-/Koordinatenprüfung bestanden. Der nächste Schritt scheiterte zunächst ausschließlich an einer **zu restriktiven CRS-Prüfung** im Kronenkreis-Importer: Das alte GeoJSON-Format von WFS kann ein `crs`-Attribut enthalten, obwohl EPSG:4326 verwendet wird. Dieser Importfehler ist behoben: bekannte EPSG:4326-/CRS84-Deklarationen werden akzeptiert, andere Bezugssysteme weiterhin abgewiesen. **Der WFS-Download mit 252 Punkten ist bestätigt; ein erster Kreis-/Messlauf wurde durchgeführt, aber wegen der später entdeckten Verwechslung von Kategoriecode und metrischem Klassenintervall als ungültig verworfen.** Die originale WFS-Datei bleibt unverändert im lokalen Cache.

### Korrektur der Wiener Kronendurchmesser (13.10.2026)

**Echter Datenfehler im ersten Kronenprovider:** Die erste Version behandelte das numerische Feld `KRONENDURCHMESSER` als **Meterwert**. Dieses Feld ist tatsächlich ein **Kategoriencode**. Die Meterbereiche stehen in `KRONENDURCHMESSER_TXT` (etwa `16-18 m`). Die 252 erfolgreich heruntergeladenen WFS-Punkte waren korrekt, aber ihre Kronenradien wurden falsch abgeleitet.

**Erster lokaler Lauf – ausdrücklich ungültig:** 117 erzeugte Kronenkreise, 536,88 m² Überschirmung und **1,15 %** von 46.630,56 m² Straßenraum sind **verworfen**. Die Werte dürfen nicht als Ergebnis von Variante A oder als Vergleichsmaßstab verwendet werden.

**Neue Klassenauswertung:** Für **geschlossene Meterintervalle** der Form `a-b m` (auch Gedankenstriche, Abstände, Dezimalkomma) gilt `Durchmesser = (a+b)/2`. Beispiel: `16-18 m` → **17 m angenommener Durchmesser**, Kreisradius **8,5 m**. Dies ist **kein exakter Messwert** eines individuellen Baums, sondern eine deklarierte Näherung aus der Klasse. Die Klasse im Originaltext sowie der numerische Kategoriencode werden im Kronen-GeoJSON zur Prüfung aufbewahrt; die Häufigkeiten der Quellklassen stehen im Bericht.

**Keine stille Rückfallregel:** Wenn der Text fehlt, offen ist (z. B. `über 21 m`), nicht eindeutig geparst werden kann oder außerhalb der Plausibilitätsgrenzen liegt, wird **kein Kreis aus dem Kategoriencode** erzeugt. Solche Bäume werden gezählt und bleiben zunächst unberücksichtigt. Vor einer späteren Behandlung offener Klassen müssen wir die **tatsächlich im WFS vorkommenden Werte** und die gewünschte Schätzstrategie prüfen.

**Erneuter Lauf:** Nur der Kronenprovider und die Messung müssen wiederholt werden; der lokale WFS-Download bleibt gültig. Danach die Zahl verwertbarer Kronen, den Ausschlussbericht und die Kronenkreise visuell prüfen und **erst dann** den neuen Überschirmungsgrad als Referenz dokumentieren.


## Erste Testreihe: Ansatz A

Voraussetzung: FMZK-Testausschnitt aus Modul 1 und `fmzk_strassenraum.geojson` aus Modul 2.


```bash
./scripts/update-and-sync.sh
.venv/bin/python -m scripts.fetch_vienna_trees  # nur bei fehlendem WFS-Cache nötig
.venv/bin/python -m scripts.build_canopy_circles --wien data/processed/baumkronen/baumkataster_wfs.geojson
.venv/bin/python -m scripts.measure_canopy_cover
```

**Nach dem erfolgreichen WFS-Download vom 13.10.2026:** Nach `./scripts/update-and-sync.sh` reichen die letzten **beiden** Befehle (`build_canopy_circles`, `measure_canopy_cover`); den Download nicht unnötig wiederholen. Falls weiterhin ein CRS-Fehler erscheint, die `crs`-Deklaration der WFS-Datei kontrollieren, statt das Attribut ohne Prüfung zu löschen.

Dateien:

- `data/processed/baumkronen/baumkataster_wfs.geojson` und `baumkataster_wfs_bericht.json`: rohe, lokal gespeicherte städtische Baum-Punkte.
- `data/processed/baumkronen/baumkronen_kreise.geojson` und `baumkronen_kreise_bericht.json`: erzeugte metrische Kronenkreise und Ausschluss-/Dublettenstatistik.
- `data/processed/ueberschirmung/ueberschirmung_bericht.json` und `ueberschirmte_flaeche.geojson`: **Überschirmungsgrad** und zur Sichtkontrolle an der Straßenmaske beschnittene Kronenunion.

Zunächst die Ergebnisse mit einem aktuellen Orthofoto und dem Baumkataster der Kartensammlung vergleichen. **Nicht bereits einen stadtweiten Prozentwert extrapolieren.**

### Erster lokaler Messlauf mit korrigierten Kronenklassen (13.10.2026)

Nach der Korrektur auf `KRONENDURCHMESSER_TXT` und der Verwendung des **Mittelwerts geschlossener Meterintervalle** wurde Methode **A – Wiener Baumkataster als Kronenkreise** im selben Testausschnitt erneut ausgeführt. Die folgende Ausgabe wurde lokal gemeldet:

| Kennzahl | Neuer Wert |
| --- | ---: |
| Straßenraum (gleiche vorläufige Maske wie Modul 3) | **46.630,56 m²** |
| Vereinte Baumkronenfläche über dem Straßenraum | **3.647,05 m²** |
| **Überschirmungsgrad** | **7,82 %** |
| Generierte Kronenkreis-Features | **117** |
| Zuvor per WFS geladene Baumkataster-Punkte | **252** |
| Gemeldete mögliche OSM/Wien-Dubletten | **0** |

**Ergebnisprüfung anhand des lokalen Kronenkreis-Berichts:** Die Differenz von **135 Bäumen** ist inzwischen vollständig erklärt. Es handelt sich dabei nicht um 135 unerklärte oder verlorene Kronen:

| Auswahl/Ausschluss | Baumstandorte |
| --- | ---: |
| Vom WFS geladen | **252** |
| Ohne bestimmbaren Kronendurchmesser: `nicht bekannt` | −20 |
| Offene Kronenklasse `>21 m` (nicht als Intervallmittelwert darstellbar) | −1 |
| **Mit verwertbarer, geschlossener Kronenklasse** | **231** |
| Punkt außerhalb des räumlichen Untersuchungsbereichs für Kronenkreise | −57 |
| Kreis ohne Flächenkontakt zum FMZK-Testgebiet | −57 |
| **Erzeugte Kronenkreise mit Kontakt zum Testgebiet** | **117** |

**Die Kronenklassen-Häufigkeiten der 252 WFS-Punkte** sind: `0-3 m`: **79**, `4-6 m`: **49**, `7-9 m`: **51**, `10-12 m`: **40**, `13-15 m`: **7**, `16-18 m`: **5**, `>21 m`: **1**, `nicht bekannt`: **20**. Summe: **252**. Damit sind **231/252 = 91,67 %** der WFS-Bäume mit einer auswertbaren Größenklasse versehen; die verbliebenen **114** Abgänge aus dieser Gruppe sind vollständig durch räumliche Filter erklärt. Die WFS-Abfrage enthält **absichtlich einen Randbereich** um das Testgebiet, um hineinragende Kronen nicht abzuschneiden.

**Wichtig zur Interpretation:** „117 erzeugte Kronenkreise“ heißt lediglich, dass diese Kreise das **FMZK-Testgebiet** berühren. Es beweist **nicht**, dass alle 117 Bäume den *Straßenraum* überschirmen. Der gemessene Überschirmungsgrad von **7,82 %** beruht auf der **vereinigten Fläche aller Kronen ∩ Straßenraum**, nicht auf der Zahl der Kreise. Die 57 + 57 räumlich ausgeschlossenen Bäume stellen **keine Datenverluste** dar. **0 OSM/Wien-Dubletten** ist ohne OSM-Eingabe kein aussagekräftiger Dublettencheck.

**Offene methodische Unsicherheit:** Wir wissen aus diesem zusammenfassenden Bericht nicht, **ob die 20 Bäume ohne bekannte Kronenklasse oder der einzelne Baum in der offenen Klasse `>21 m` überhaupt Kronen über dem Straßenraum hätten**. Falls ja, kann die derzeitige Flächenschätzung zu niedrig sein. Keine improvisierte Pauschalschätzung, sondern erst diese Fälle räumlich prüfen. Die Klassendurchmesser sind ohnehin nur **Intervallmittelwerte** und kreisförmige Kronen eine Näherung.

**Bewertung:** Der korrigierte Lauf von **3.647,05 m² bzw. 7,82 %** ist als **vorläufiger Referenzlauf für Ansatz A** verwendbar; die ehemals gemeldeten **536,88 m² bzw. 1,15 % sind verworfen**. Die rein numerische Vollständigkeitsfrage ist geklärt. Für eine **fachlich validierte** Genauigkeit fehlen weiterhin die Sichtprüfung der Kronenpolygone auf einem geeigneten Orthofoto, insbesondere an den Straßenrändern, und der unabhängige Vergleich mit OSM bzw. Grünraummonitoring 2023.

**Nächste Qualitätskontrolle:**

1. Die 117 Kreise und die aus ihnen abgeleitete **tatsächlich überschnittene Straßenraumfläche** auf einem Orthofoto prüfen. Ein Kreis kann im Testgebiet liegen, ohne eine Straßenfläche zu treffen.
2. Bei Bedarf für die **21 Bäume ohne verwertbaren Klassenwert** getrennt untersuchen, ob ihr Standort innerhalb oder nahe genug an der Straßenraumfläche liegt, um die Quote beeinflussen zu können. Das erfordert die Punkte bzw. einen ergänzten diagnostischen Lauf, ist aus diesem Bericht nicht ableitbar.
3. Für den methodischen Vergleich mit **B (Wien + OSM)** und **C (Grünraummonitoring 2023)** denselben Straßenraum und dieselbe Berechnung verwenden. Mehr erfasste Kronenfläche bedeutet nicht automatisch bessere Genauigkeit.

**Unverändert:** Die Kennzahl **Bodenbegrünungsanteil 1,91 %** aus Modul 3 ist davon getrennt. Die beiden Prozentwerte dürfen wegen räumlicher Überlagerung nicht addiert werden.

## Zweite Testreihe: Ansatz B (OSM ergänzen)

Lokale OSM-Daten benötigen **GeoJSON-Punkte** für `natural=tree`. Sie können unabhängig bereitgestellt werden. Baumreihen `natural=tree_row` werden derzeit **bewusst nicht künstlich in Einzelbäume umgewandelt**; eine solche räumliche Approximation müsste separat geprüft werden.


```bash
# Wien-Only-Ausgabe für den Vergleich erhalten
.venv/bin/python -m scripts.build_canopy_circles \
	--wien data/processed/baumkronen/baumkataster_wfs.geojson \
	--out-dir data/processed/baumkronen/variante_wien

# OSM-Punkte mit realem Kronendurchmesser ergänzen
.venv/bin/python -m scripts.build_canopy_circles \
	--wien data/processed/baumkronen/baumkataster_wfs.geojson \
	--osm data/processed/baumkronen/osm_baeume.geojson \
	--out-dir data/processed/baumkronen/variante_kombiniert

# Dann beide Varianten gegen dieselbe Straßenraum-Maske vergleichen
.venv/bin/python -m scripts.compare_canopy_methods \
	--candidate wien=data/processed/baumkronen/variante_wien/baumkronen_kreise.geojson \
	--candidate kombiniert=data/processed/baumkronen/variante_kombiniert/baumkronen_kreise.geojson
```

**Regeln:** Bäume ohne verwertbaren Kronendurchmesser werden normalerweise **ausgelassen und gezählt**. Die bewusst nicht standardmäßig gewählte Option `--osm-default-diameter-m 5` führt dagegen eine eigene **geschätzte** Variante ein; im Bericht sichtbar markieren, nicht mit gemessenen Daten verwechseln. OSM-Punkte binnen **2 m** eines Wien-Punkts werden als **mögliche Dubletten** protokolliert und für die Kombivariante nicht doppelt gezählt. Das ist ein vorläufiger Näherungswert, kein garantierter identischer Baum; Ausschlüsse gezielt prüfen. Baumstämme auf privaten Grundstücken können dennoch Kronen über Straßen beitragen.

Die A/B-Gegenüberstellung ist zunächst nur möglich, wenn eine geeignete OSM-GeoJSON-Datei bereitgestellt wird. **Es gibt im Repo noch keinen fertig geprüften OSM-Downloaddienst.** Eine später angebotene kombinierte Tilequelle könnte dafür als eigener weiterer Quelladapter dienen, ohne das Messmodul zu verändern.

## Variante C: Grünraummonitoring 2023 – WMS-Diagnose und Kronenprovider

**Datengrundlage:** Grünraummonitoring 2023 der Stadt Wien, Rasterbasis 50 cm, **Baumschicht als thematische Klasse 3**. Der WMS-Ebenenname ist **`GRM2023OGD`**, Dienst **`https://data.wien.gv.at/daten/wms`**. Die amtliche Methodik verwendet 2023er Sommer-Infrarotbilder und Höhendaten; diese Quelle unterscheidet sich grundlegend von der Kreisapproximation des Baumkatasters.

**Wichtige Unterscheidung:** „Baumschicht = Klasse 3“ bezeichnet die **fachliche Klasse des Quellrasters**, nicht unmittelbar den PNG-Pixelwert. Für **das tatsächlich diagnostizierte WMS-Bild** ist jetzt durch neun exakt vorkommende Rasterfarben und die mitgelieferte Legende belegt, dass **#38A800** die Baumschicht darstellt. Eine andere oder geänderte WMS-Ausgabe darf dennoch nicht ungeprüft dieselbe Farbzuordnung übernehmen.

### Schritt C1 – Metadaten, Legende und Test-Raster sichern

**Neues, isoliertes Modul:** `scripts/probe_grm2023_wms.py`. Die Berechnung aus `scripts/measure_canopy_cover.py` und die Straßenraum-Maske aus Modul 2 werden **nicht geändert**.

```bash
./scripts/update-and-sync.sh
.venv/bin/python -m scripts.probe_grm2023_wms
```

Voraussetzung: das lokale `data/processed/fmzk_test.gpkg` mit zugehörigem `fmzk_test.json`.

Unter `data/processed/baumkronen/grm2023/` entstehen:

- **`getcapabilities.xml`** – unveränderte WMS-Metadaten einschließlich der angebotenen Projektionen und Stile.
- **`grm2023_testausschnitt.png`**, **`.pgw`** und **`.prj`** – originale PNG-GetMap-Antwort für das Testgebiet plus 10 m Puffer, mit Pixel-/Weltkoordinaten- und CRS-Angabe für die genaue Kontrolle in QGIS.
- **`grm2023_legende.png`** – falls der WMS sie tatsächlich als PNG liefert; Fehlen ist als Diagnose-Status dokumentiert und verhindert nicht den Raster-Abruf.
- **`grm2023_wms_diagnose.json`** – WMS-Layer/SRS, Abfrageparameter, SHA-256, BBOX/Pixelabmessungen, Bildmodus, Anzahl und Häufigkeiten der RGBA-Farben, Transparenz-/Legendenstatus.

Es wird die vom WMS deklarierte **EPSG:31256**-Projektion bevorzugt, sonst **EPSG:3857**; kein unkontrolliertes Achsentauschen. Standardmäßig wird für den kleinen Ausschnitt ein etwa 0,5-m-**Anfragegitter** gewählt, mit striktem Limit für Bildbreite/-höhe und Antwortgröße. **Die Anfrage-Pixelgröße entspricht nicht zwingend der nativen Rasterauflösung.** BBOX und tatsächliche Pixelbreiten sind für eine spätere quantitative Auswertung exakt mitzunehmen.

Das Modul **berechnet noch keine Baumkronenfläche und erzeugt absichtlich kein Kronen-GeoJSON**, solange wir nicht sicher wissen, welche Farben/Pixelwerte der Klasse 3 entsprechen. Der Code verweigert Nicht-PNG-Antworten (z. B. XML-WMS-Fehlermeldungen) und unerwartete Bildabmessungen, anstatt sie als gültige Rasterdaten zu behandeln. Die Abfrage gegen den **echten Wiener Dienst ist von GitHub Actions nicht erreichbar** und muss lokal überprüft werden.

**Die lokalen Diagnose-Dateien wurden bereitgestellt und geprüft.** Die dabei bestätigte Klassenzuordnung und ihre Verwendung im eigenständigen Provider sind im folgenden Abschnitt dokumentiert.

### Schritt C2 – Baumschichtfarben anhand der echten WMS-Ausgabe bestätigt

**Diagnose der vom Nutzer lokal abgerufenen Dateien (13./14.10.2026):**

- WMS-GetMap: `GRM2023OGD`, `EPSG:31256`, **923 × 858 Pixel = 791.934 Pixel**.
- **Genau neun RGBA-Farben**, alle Pixel vollständig deckend. Keine Mischfarben oder Transparenzen in diesem Testbild.
- Die WMS-Legende unterscheidet **Grasschicht**, **Strauchschicht** und **Baumschicht**. Die Baumschicht ist das **dunkelgrüne Raster-RGB `#38A800` (56,168,0)**. Die Legenden-Symbole weichen teilweise um 1–2 RGB-Stufen ab, die neun Klassen sind jedoch eindeutig zuzuordnen; das Programm verwendet **ausschließlich die tatsächlich vorliegenden GetMap-Farben** und keine Näherung.
- Pixel der **Baumschicht: 71.892**; alle zusammen belegen im **gesamten WMS-Anfragebild** rund **17.958,20 m²**. Dieser Wert ist **nicht** die Kronenüberschirmung des Straßenraums.
- Die tatsächliche WMS-Pixelbreite beträgt rund **0,49969 m** und die Pixelhöhe **0,49990 m**. Diese Rasterzellen des WMS-**Anfragegitters** werden geometrisch verarbeitet; eine 1:1-Übereinstimmung mit originalen 50-cm-Rohdaten oder eine vermessene Kronengrenze wird nicht behauptet.
- Die exakten Bild- und Legenden-SHA-256 werden gegen `grm2023_wms_diagnose.json` geprüft. Bei anderen Farben, transparenten Pixeln, fremder Projektion oder abweichendem Worldfile wird die Polygonerzeugung **abgebrochen**.

### Schritt C3 – Eigenständiger Kronenprovider für das WMS-Raster

**Implementiert:** `scripts/build_canopy_grm2023.py`. Der Provider liest den gesicherten Diagnoseordner und verwandelt zusammenhängende Baum-Pixelzellen in echte, metrisch korrekt verortete Polygone. Dafür werden horizontal aufeinanderfolgende Baum-Pixel erst als gemeinsame Rechtecke („Runs“) und dann geometrisch vereinigt – kein willkürliches Glätten, Buffering oder Schätzen aus anderen Grünklassen. Nur **Baumschicht** zählt; Gras und Sträucher werden ausgeschlossen.

```bash
./scripts/update-and-sync.sh
.venv/bin/python -m scripts.build_canopy_grm2023
```

Outputs unter `data/processed/baumkronen/grm2023/processed/`:

- `baumkronen_grm2023.geojson` – **eine** `FeatureCollection` mit einem `Polygon`/`MultiPolygon`-Feature, EPSG:4326, als **austauschbare Kronen-GeoJSON-Maske** für das vorhandene Modul `measure_canopy_cover.py`.
- `baumkronen_grm2023_bericht.json` – Flächen, Pixelzahlen, geometrische Teilstücke, Rastermaß, alle WMS-Klassen sowie Hashes der Datenquellen.

**Überschirmungsgrad berechnen**, ohne Modul 2/3/4-Messlogik zu ändern:

```bash
.venv/bin/python -m scripts.measure_canopy_cover \
	--crowns-geojson data/processed/baumkronen/grm2023/processed/baumkronen_grm2023.geojson \
	--out-dir data/processed/ueberschirmung/grm2023
```

**Beide Methoden A und C direkt vergleichen** (identische Straßenraum-Maske):

```bash
.venv/bin/python -m scripts.compare_canopy_methods \
	--candidate baumkataster=data/processed/baumkronen/baumkronen_kreise.geojson \
	--candidate grm2023=data/processed/baumkronen/grm2023/processed/baumkronen_grm2023.geojson
```

**Beide Varianten wurden inzwischen lokal ausgeführt und verglichen:** Variante A ergibt **7,82 %**, Variante C **9,35 %** Überschirmung der identischen Straßenmaske. Die **17.958 m²** Baumfläche des vollständigen WMS-Bilds bleiben ausdrücklich vom **Straßenraum-Schnitt (4.358,69 m²)** getrennt. Vollständige Ergebnisse, SHA-256 und methodische Einschränkungen stehen im anschließenden Referenzlauf.

**Noch zu kontrollieren:** Wie gut folgt das gerenderte WMS-Bild den wirklichen Baumkronengrenzen? Die WMS-Farbklassen sind im Testbild eindeutig, aber der Dienst kann das Originalraster intern resamplen. Unterschiede zu Kronenkreisen müssen im Orthofoto und besonders an Straßenrändern überprüft werden. Eine höhere Fläche oder IoU allein beweist keine höhere Genauigkeit.

### Verbleibende Validierung

1. **Raster gegen Orthofoto prüfen:** Im Straßenraum und an Kreuzungen kontrollieren, ob die WMS-Baumschicht der real sichtbaren Kronenfläche hinreichend gut folgt und wo zeitliche Unterschiede zwischen 2023 und aktuellem Baumkataster auftreten.
2. **Berechneten Methodenvergleich räumlich überprüfen:** A = 7,82 %, C = 9,35 %, IoU = 58,02 %. Besonders die 707,44 m² nur in A und 1.419,08 m² nur in C über Orthofoto und Straßenraum prüfen; dazu möglichst eigene Differenz-GeoJSONs exportieren.
3. **Pixelgenauigkeit vorsichtig interpretieren:** Die WMS-Ausgabe ist ein gerendertes Bild. Die fachliche 50-cm-Quellauflösung ist nicht automatisch ein Beleg für unveränderte 50-cm-Rohpixel im GetMap-Ausschnitt. Bei auffälligen Artefakten suchen wir besser die ursprünglichen kategorialen Rasterdaten, statt eine künstliche Exaktheit anzunehmen.
4. **Datenänderungen absichern:** Ein zukünftiger WMS mit neuer Farbpalette, BBOX, Alpha oder Klassifikation muss neu diagnostiziert und seine Klassenabbildung überprüft werden.

**Status:** C1 (WMS-Diagnose), C2 (Farb-/Klassenprüfung) und C3 (Polygonprovider) sind im Testausschnitt erfolgreich ausgeführt. Die unveränderte Straßenraum-Schnittberechnung und der Methodenvergleich A/C liegen ebenfalls vor. **Offen bleiben die kartografische Sichtprüfung und eine unabhängige Genauigkeitsbewertung.** Eine bevorzugte Standardmethode wird erst danach festgelegt. Variante D (eigene Infrarot-Segmentierung) bleibt eine spätere Option.

## Erster vollständiger lokaler Referenzvergleich A/C (13.–14.10.2026)

Dieser Abschnitt dokumentiert die **tatsächlich lokal ausgeführten Ergebnisse** aus:

- `data/processed/baumkronen/grm2023/processed/baumkronen_grm2023_bericht.json` (Erzeugung der WMS-Polygonmaske; 13.10.2026, **22:17:59 UTC**);
- `data/processed/ueberschirmung/grm2023/ueberschirmung_bericht.json` (Straßenraum-Schnitt; 13.10.2026, **22:18:00 UTC**);
- `data/processed/ueberschirmung/vergleich/kronenmethoden_vergleich.json` (A/C-Vergleich; 13.10.2026, **22:18:01 UTC**);
- dem bereits geprüften Baumkataster-Lauf A mit 117 Kronenkreisen.

Die Ergebnis-JSONs und ihre GeoJSON-Daten bleiben weiterhin **lokal unter `data/`**; nur die Referenzkennzahlen und Methodeninformationen stehen hier im Repository.

### Pixel-zu-Polygon-Prüfung von C

| Prüfung | Verifiziertes Ergebnis |
| --- | ---: |
| WMS-Ebene und Fachklasse | `GRM2023OGD`, **Baumschicht Klasse 3**, Farbe **`#38A800`** |
| EPSG / PNG-Abmessungen | **31256**, **923 × 858 = 791.934 Pixel** |
| Summe sämtlicher neun Rasterklassen | **791.934 Pixel** |
| Davon Baumschicht | **71.892 Pixel** |
| Größe einer Anfrage-Rasterzelle | **0,2497941962 m²** |
| Baumfläche, aus Zellzahl berechnet | **17.958,204354872 m²** |
| Baumfläche nach metrischer Raster-Polygonisierung | **17.958,204354872 m²** |
| Flächenabweichung bei der Polygonisierung | **unter 0,000000001 m²** |
| Zusammengefasste horizontale Zellläufe | **7.578** |
| Getrennte Polygonbestandteile | **1.298** |
| GeoJSON-Ausgabe | **1 MultiPolygon-Feature**, enthält diese Teilflächen |

**Einordnung:** Die Rasterzellen wurden durch das Polygonisieren weder doppelt gezählt noch flächenmäßig verändert. Eine GeoJSON-Konvertierung über WGS84 und zurück nach EPSG:31256 liefert in der späteren Messung **17.958,204428868 m²** Gesamt-Kronenunion; die Differenz von rund **0,000074 m²** gegenüber der Quellprojektion ist für diese Gebietsgröße vernachlässigbar. Diese Rechenübereinstimmung prüft **die Verarbeitung**, nicht die Genauigkeit der GRM-2023-Klassifikation gegenüber tatsächlichen Kronengrenzen.

### Beide Methoden auf demselben Straßenraum

**Nenner:** Vereinigungsfläche von **487 Straßenraum-Features**, **46.630,560980 m²**. Die Straßenmaske ist für beide Läufe identisch; ihre SHA-256-Prüfsumme lautet:

`dc53cd78d0bcd5cb242529e126a969f1be6ca5d27487ff1e85ee684654d7fc11`

| Kennzahl | A – Wiener Baumkataster | C – GRM 2023 |
| --- | ---: | ---: |
| Eingabe-Kronengeometrie | 117 Kreise (je 1 Polygon-Feature) | 1 MultiPolygon-Feature (1.298 Einzelteile) |
| Kronenunion vor Straßenraum-Schnitt | **4.777,20 m²** | **17.958,20 m²** |
| **Baumkronen über Straßenraum** | **3.647,05 m²** | **4.358,69 m²** |
| **Überschirmungsgrad** | **7,8212 %** | **9,3473 %** |
| Baumkronenunion außerhalb Straßenraum | 1.130,15 m² | 13.599,51 m² |

**Differenz C gegenüber A:** **+711,64 m²** Kronenfläche über Straßenraum, **+1,5261 Prozentpunkte** bzw. rund **19,5 % relativ zur A-Fläche**. Die außerhalb des Straßenraums liegende Kronenunion ist **keine fehlende Straßenraumfläche** – Methode C klassifiziert auch die privaten Grün- und Baumbereiche des vollständigen WMS-Ausschnitts.

### Räumlicher Vergleich *innerhalb* des Straßenraums

| Schnittfläche | Fläche |
| --- | ---: |
| **Von A und C gemeinsam erkannt** | **2.939,61 m²** |
| **Nur A / Baumkataster** | **707,44 m²** |
| **Nur C / Grünraummonitoring 2023** | **1.419,08 m²** |
| **Vereinigung A ∪ C im Straßenraum** | **5.066,14 m²** |
| **Intersection over Union (IoU)** | **0,5802465533 = 58,02 %** |

Die beiden Methoden stimmen in vielen Bereichen überein, weichen aber **deutlich** voneinander ab. Die IoU ist eine **gegenseitige Ähnlichkeit**, keine Genauigkeit gegen reale Kronen. Aus „C zeigt mehr“ folgt **nicht** „C ist zuverlässiger“. Neben kreisförmigen A-Geometrien und echten bzw. klassifizierten Vegetationsformen in C unterscheiden sich auch Datenjahr, Erhebungsmethodik, Lagegenauigkeit, Abdeckung privater Bäume und WMS-Pixelraster. **Es gibt weiterhin keine unabhängige manuelle Validierung.**

### Reproduzierbare Eingaben und Vergleichbarkeit

- **Kronen A (Wiener Baumkataster):** `data/processed/baumkronen/baumkronen_kreise.geojson`, SHA-256 `a0122c28e52b2ec03daa68d2fcdf7004a37adfc71485bd7c8bd4ac8d745033ac`.
- **Kronen C (GRM2023):** `data/processed/baumkronen/grm2023/processed/baumkronen_grm2023.geojson`, SHA-256 `a19acbe53ad58c0fd39000ee53dab5309e104827eb0e08e18ef49bc2aa1532ea`.
- **WMS-Quellbild:** `data/processed/baumkronen/grm2023/grm2023_testausschnitt.png`, SHA-256 `076abd2fdf4159347c426792858c553ece48d4b89e792d27a632b6418bc9ee73`.
- **WMS-Diagnose:** SHA-256 `f9446dca814cd58036c2e81c5c27e959e23f9c3cd0b5ff487da9eae788f6bac7`; **WMS-Legende:** SHA-256 `a0e2250f45929ff04d0b208b7c45678b0ca44f440762a8375b08abf00919c403`.
- **Vergleichsskript:** `scripts/compare_canopy_methods.py`; nach identischer Straßenraum-Maske bereits ausgeführt. Die PNG-/GeoJSON-Hashes dienen der **Versionierung des konkreten lokalen Datenstands**.

**Wichtig für die nächste Iteration:** Unsere nächste Aufgabe ist **nicht**, ohne Sichtprüfung eine Methode zum Sieger zu erklären, sondern die drei Differenzflächen `A ∩ C`, `A \ C` und `C \ A` **auf dem Straßenraum** als separate GeoJSON-Layer zu exportieren und über ein Orthofoto zu legen. Gerade an Straßenbäumen, privaten Kronenüberhängen und Kreuzungen lässt sich dann unterscheiden, ob es sich um Modellvereinfachung, fehlende Baumdaten oder GRM-Pixelklassifikation handelt. Erst danach über die bevorzugte Methode oder eine Hybridvariante entscheiden.

## Langfristige Modularität

Alle Kronenprovider sollen dieselbe **Kronen-Geometrieschnittstelle v1** bedienen: GeoJSON FeatureCollection, Polygon/MultiPolygon, EPSG:4326; Attribute optional. Modul 4 (Messung) importiert keinen der Provider. Die Straßenraum-Eingabe bleibt die bereits in [Modulare Architektur](Modulare-Architektur.md) vereinbarte Schnittstelle von Modul 2.

Das Vergleichsmodul berichtet bewusst **Unterschiede**, nicht „der beste Ansatz“. Ohne unabhängige Referenzflächen (z. B. manuell geprüfte Kronenumrisse über Sommerorthofotos) kann kein Verfahren allein auf Basis einer größeren Überschirmungsquote als genauer bezeichnet werden. Beim Wechsel des Standardproviders und bei Änderungen an der Straßenraum-Maske Vergleichsversion und SHA-256 erhalten.

Quellinformationen: [Stadt Wien – Baumkataster](https://www.wien.gv.at/umwelt/stadtbaeume); [data.gv.at – Grünraummonitoring 2022](https://www.data.gv.at/datasets/684d2bbd-9bb7-319c-acb6-c1120e74e123?locale=de); [data.gv.at – OGD Update 09/2026](https://www.data.gv.at/ogd-update-wien-092026/); [BEV – Orthophoto Farbe](https://www.bev.gv.at/Services/Produkte/Luftbildprodukte/Orthophoto-Farbe.html).
