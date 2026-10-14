# Modul 4: Baumkronen und Überschirmungsgrad – modulare Vergleichsstrecke

**Stand:** 14. Oktober 2026. **Status:** Die unabhängigen Kronenprovider **A (Wiener Baumkataster), B (Wien + OSM) und C (Grünraummonitoring 2023)** wurden im selben Straßenraum lokal ausgeführt und die Flächenwerte dokumentiert: **7,82 %, 7,89 % bzw. 9,35 %**. Räumliche IoU: **A/B 99,14 %, A/C 58,02 %, B/C 57,67 %**. Der WMS-Kronenexport stimmt flächenmäßig mit den 71.892 klassifizierten Pixeln überein. **Die fachliche Genauigkeit der beiden Verfahren ist noch nicht anhand unabhängiger Referenzflächen validiert.** Die Straßenraum-Abgrenzung aus Modul 2 und die Bodenbegrünung aus Modul 3 bleiben unverändert.

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
| **B – Wien + OpenStreetMap** | Wien-WFS plus OSM `natural=tree` und `natural=tree_row` nach der bestehenden Kartensammlungs-Merge-Logik | Originalpriorität, **4-m-Dubletten**, Baumreihensampling (**8 m**); fehlende OSM-Kronen explizit als Solar-Schätzungen markiert | **Erster echter lokaler Lauf: 7,89 %; Baumreihen im Testgebiet nicht vorhanden** |
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

## Variante B: Wiener Baumkataster + OSM – jetzt strikt getrennt

### Quellimplementierung der Kartensammlung

Die ursprüngliche Datenzusammenführung befindet sich **nicht im Frontend**, sondern im eigenen Repository:

- [`kartensammlung-overlay-builds/baumkataster/build.mjs`](https://github.com/peter-alexander/kartensammlung-overlay-builds/blob/main/baumkataster/build.mjs) – tatsächliche Merge-, Dubletten- und Samplinglogik;
- [`baumkataster/README.md`](https://github.com/peter-alexander/kartensammlung-overlay-builds/blob/main/baumkataster/README.md) – Dokumentation der Quellen, der Tags, der Baumreihen und des Vektorkachel-Builds;
- [`SolarViennaTrees.js` (alte MapLibre-Kartensammlung)](https://github.com/peter-alexander/kartensammlung-maplibre/blob/main/Components/SolarViennaTrees.js) – bisherige transparente Größenschätzung für OSM-Bäume, deren Kronendurchmesser nicht gemappt ist.

Der externe Build bereitet alle Wiener Bäume für ein kombiniertes Vektor-Tileset und die 3D-Schattenberechnung auf. **Das Karten-Frontend selbst enthält keine vollständige OSM-Dublettenlogik**, sondern liest diese bereits vereinigten Kacheln. Die bisherige, nur für die Analyse geschriebene OSM-Option in `build_canopy_circles.py` basierte dagegen auf einem unzureichenden 2-m-Nachbarschaftstest und enthielt keine Baumreihen; sie ist **aus Methode A entfernt**. Diese alte Option soll **nicht mehr** für B verwendet werden.

### Saubere Modultrennung

| Rolle | Methode A | Methode B |
| --- | --- | --- |
| Startskript | `scripts/build_canopy_circles.py` | **`scripts/build_canopy_combined.py`** |
| Quellen | Ausschließlich Wiener WFS `BAUMKATOGD` | Derselbe Wiener WFS + OSM aus Overpass |
| Download | `scripts/fetch_vienna_trees.py` | zusätzlicher **`scripts/fetch_osm_trees.py`** |
| Gemeinsame Geometriehelfer | `scripts/canopy_tree_common.py` | derselbe *reine* Hilfsbaustein |
| Spezifische Zusammenführung | keine | **`scripts/canopy_osm_merge.py`** |
| Default-Kronenausgabe | `data/processed/baumkronen/baumkronen_kreise.geojson` | `data/processed/baumkronen/variante_b/baumkronen_kombiniert.geojson` |
| Aufruf der Flächenmessung | bestehendes `measure_canopy_cover.py` | **unverändert dasselbe** Skript |
| Stand | Lokaler Referenzlauf: **7,82 %** | **Echter Overpass-/Vergleichslauf abgeschlossen: 7,89 %** |

A akzeptiert **keinen OSM-Dateipfad mehr**. Die Wiener Kronenpolygone von A bleiben auch als **Wiener Teilmenge von B** geometrisch identisch, sofern beide dieselben Wiener Quelldaten und FMZK-Testgeometrien erhalten. Dies ist in einem Integrationstest abgesichert. B schreibt **eigene** GeoJSON-Dateien und Berichte; weder A noch C werden verändert.

### Aus der Kartensammlung übernommene Regeln

**Priorität:**

1. Wiener Baumkataster: Primärquelle; auch **Bäume ohne brauchbare Kronenklasse** besetzen einen bekannten Standort im Dublettenindex.
2. OSM `node[natural=tree]`: nur ergänzen, wenn innerhalb von **4 m** kein Wiener Punkt liegt; weitere OSM-Nodes innerhalb von **0,75 m** werden dedupliziert.
3. OSM `way[natural=tree_row]`: in mögliche Einzelpositionen auflösen; gegen Wien **4 m**, gegen explizite OSM-Einzelbäume **4 m** und gegen bereits berücksichtigte Baumreihen-Samples **3 m** prüfen.
4. Baumreihen mit `tree_count` bzw. `trees` in genau diese Anzahl Teilpositionen zerlegen (bis 500); ohne Anzahl die Reihe ungefähr alle **8 m** abtasten (bis 500). Bei einer bekannten Mehrzahl werden die **Endpunkte** eingeschlossen, beim 8-m-Fallback Positionen zwischen den Reihenenden gesetzt.

**Abweichung, bewusst dokumentiert:** Der ursprüngliche JS-Build nutzt für kurze Abstände eine vereinfachte WGS84-Meterskalierung bei Referenzbreite Wien. Die Analyse verwendet stattdessen EPSG:31256, was für die Flächenberechnung präziser und methodisch konsistent ist. Das kann bei Grenzfällen im Zentimeterbereich die Entscheidung ändern.

**Kronendurchmesser:**

- Wien verwendet **unverändert** die aktuelle, bereits geprüfte Methode A (`KRONENDURCHMESSER_TXT` → Intervallmittelwert). Keine neue Abschätzung fehlender Wiener Größen in B, damit die Wiener Teilmenge identisch bleibt.
- OSM: `diameter_crown`, `crown:diameter` und alternativ `crown_diameter` werden vorrangig als **explizite metrische Maße** gelesen, einschließlich `m`, `cm`, `mm` oder `ft`. Anders als der tolerante Parser des Builds wird bewusst **kein uneindeutiger Freitext stillschweigend interpretiert**.
- Fehlt ein explizites OSM-Kronenmaß, verwendet B standardmäßig eine **klar gekennzeichnete Schätzung aus dem Solar-3D-Modell**: OSM-Höhe (falls vorhanden), sonst **angenommene 12 m**; Kronendurchmesser zunächst **0,5 × Höhe**, begrenzt auf **2–12 m** und zusätzlich maximal **1,2 × Höhe**. Solche Kreise sind **keine beobachteten Kronen** und werden sowohl im GeoJSON (`diameter_status`, `kronendurchmesser_geschaetzt`) als auch im Bericht gezählt.
- **Vergleichsoption:** `--strict-osm` schließt OSM-Bäume ohne explizite Kronendurchmesser aus. Sie erzeugt eine **andere Untervariante** von B; für ein späteres Ergebnis muss dieser Parameter mit dokumentiert werden.
- Besonderheit der 2D-Flächenanalyse: Explizite OSM-Durchmesser werden **nicht auf eine aus angenommener Höhe abgeleitete 3D-Obergrenze reduziert**. Diese fachliche Abweichung gegenüber der dreidimensionalen Schattenmodellierung ist absichtlich, damit reale OSM-Kronenangaben Vorrang behalten.

Diese Regeln sind eine **nachvollziehbare Portierung**, keine Ausführung des ursprünglichen Tippecanoe-/Tile-Builders. Eine neue OSM-Methode wird **nicht** durch die MapLibre-Bildschirmradien bestimmt.

### Lokaler erster Vergleichslauf für Methode B

Voraussetzung: Wiener WFS-Daten aus Methode A (`baumkataster_wfs.geojson`) und vorhandene Straßenraum-Maske. `fetch_osm_trees.py` lädt lokal nur einen gepufferten Ausschnitt der OSM-Objekte, nicht den ganzen Wien-Export:

```bash
./scripts/update-and-sync.sh

# Neu: Overpass lädt Einzelbäume und Baumreihen als rohes JSON
.venv/bin/python -m scripts.fetch_osm_trees

# Methode B: Kreise aus A + ergänzte OSM-Kreise, eigener Bericht
.venv/bin/python -m scripts.build_canopy_combined

# Gleiche Straßenraum-Schnittmessung wie bei A/C – separater Ausgabeordner
.venv/bin/python -m scripts.measure_canopy_cover \
	--crowns-geojson data/processed/baumkronen/variante_b/baumkronen_kombiniert.geojson \
	--out-dir data/processed/ueberschirmung/variante_b

# A/B/C mit identischer Straßenmaske vergleichen
.venv/bin/python -m scripts.compare_canopy_methods \
	--candidate baumkataster=data/processed/baumkronen/baumkronen_kreise.geojson \
	--candidate kombiniert=data/processed/baumkronen/variante_b/baumkronen_kombiniert.geojson \
	--candidate grm2023=data/processed/baumkronen/grm2023/processed/baumkronen_grm2023.geojson
```

**Lokale Eingaben:** `data/processed/baumkronen/osm/osm_baeume_overpass.json` und `baumkataster_wfs.geojson`. Der Overpass-Adapter `scripts/fetch_osm_trees.py` dokumentiert Anfrage-BBOX samt 35 m Puffer, verwendeten Endpoint, Abfrage, Anzahl der OSM-Objekte und Prüfsummen. Ein Cache wird nur bei übereinstimmenden Metadaten wiederverwendet; unvollständige/fehlerhafte Antworten werden nicht als valide gespeichert. Der Overpass-Live-Abruf ist inzwischen **im lokalen Testgebiet erfolgreich erfolgt**: 140 OSM-Nodes, davon 128 durch Wiener Punktnähe gedoppelt; die Ergebnisse sind im nächsten Abschnitt geprüft. Eine **vollständige Wien-Abfrage** und die Verarbeitung **echter Baumreihen** sind dadurch noch nicht validiert.

**Neue Ausgaben:** `data/processed/baumkronen/variante_b/baumkronen_kombiniert.geojson` und `baumkronen_kombiniert_bericht.json` mit Wien/OSM-/Reihen-/Schätzzahlen; Messbericht unter `data/processed/ueberschirmung/variante_b/`, Methodenvergleich unter `data/processed/ueberschirmung/vergleich/`. **Der erste echte B-Lauf ist inzwischen erfolgt: 7,89 % (3.678,65 m²) gegenüber A mit 7,82 %.** Die OSM-Kronenklassen und räumlichen Ausschlüsse stehen im direkt folgenden Abschnitt. Die reale Baumreihenverarbeitung konnte mangels OSM-Reihen im Testausschnitt noch nicht überprüft werden.

**Begründung für die eigene Methode B:** Die Wiener Standortüberdeckung ist nicht vollständig (z. B. private Bäume fehlen teils). OSM kann zusätzliche Standorte und Baumreihen liefern. **Vollständigkeit und Genauigkeit der OSM-Kronen sind aber keinesfalls garantiert** – insbesondere in B mit typisierten, geschätzten Durchmessern. Der Vergleich mit C und dem Orthofoto entscheidet erst später über den tatsächlichen Nutzen.


### Erster echter lokaler Referenzlauf B (13./14.10.2026)

**Nachgereichte lokale Berichte:** `data/processed/baumkronen/variante_b/baumkronen_kombiniert_bericht.json` und `data/processed/ueberschirmung/vergleich/kronenmethoden_vergleich.json`. Der Vergleich basiert auf derselben 487-Feature-Straßenraummaske (**46.630,560980 m²**, SHA-256 `dc53cd78d0bcd5cb242529e126a969f1be6ca5d27487ff1e85ee684654d7fc11`) wie A/C.

| Kennzahl | A – Wiener Baumkataster | B – Wien + OSM | C – GRM2023 |
| --- | ---: | ---: | ---: |
| Kronen-Features | 117 | **121** | 1 MultiPolygon |
| Kronenfläche im Straßenraum | **3.647,05 m²** | **3.678,65 m²** | **4.358,69 m²** |
| **Überschirmungsgrad** | **7,82 %** | **7,89 %** | **9,35 %** |

**OSM-Datenbilanz der Methode B (nicht mit Straßenraumflächen gleichsetzen):**

| Stufe | Zahl |
| --- | ---: |
| Geladene OSM-Elemente | **140**, davon 140 Einzelbaum-Nodes; **0 Baumreihen** |
| OSM-Nodes innerhalb von 4 m eines Wien-Standorts, daher unterdrückt | **128** |
| Zusätzliche OSM-Einzelbäume nach Dublettenprüfung | **12** |
| Davon mit explizit erfasstem Kronendurchmesser | **3** |
| Davon mit geschätztem Durchmesser aufgrund fehlender OSM-Höhe (12-m-Höhenannahme) | **9** |
| OSM-Kronenpolygone mit räumlichem Kontakt zum FMZK-Testgebiet | **4** (3 explizite Maße, 1 Schätzung) |
| Wiener Kronenpolygone, identisch zum A-Lauf | **117** |
| **In B insgesamt erzeugte Kronenfeatures** | **121** |

**Warum nur 4 der 12 OSM-Ergänzungen im GeoJSON erscheinen:** Die Quelle wird mit einem räumlichen Puffer abgefragt. Das Polygonmodul prüft auch Bäume knapp außerhalb des FMZK-Testausschnitts, speichert am Ende aber nur Kronen, die diesen berühren. Die zusammengefasste räumliche Filterstatistik von B lautet **64** Standorte außerhalb des Untersuchungsbereichs sowie **58** Kronen ohne Kontakt zur Gebietsfläche. Diese beiden Zahlen betreffen **Wien und OSM zusammen**, nicht ausschließlich OSM; ihre Zuordnung zu einzelnen Providern ist aus dem Bericht allein nicht rekonstruierbar. Die lokale Quellendifferenz `12 → 4` ist dennoch durch `quellen_im_ergebnis.osm_tree = 4` bestätigt.

**Gemessener Zusatznutzen im Straßenraum:**

- Von A und B gemeinsam erkannt: **3.647,052373 m²**.
- Nur von B erfasst: **31,599582 m²**; nur von A: **0 m²**.
- Gesamtfläche B: **3.678,651956 m²** = **7,888929 %** Überschirmungsgrad, also **+0,067766 Prozentpunkte** gegenüber A.
- **IoU A/B = 99,1410 %**. Das bestätigt räumlich: B **erhält den vollständig gemessenen A-Anteil** und ergänzt nur wenige Flächen.
- **IoU B/C = 57,6710 %** gegenüber **IoU A/C = 58,0247 %**. Die Unterschiede zum Grünraummonitoring wurden durch OSM im Testgebiet also **nicht aufgelöst**.

**Versionierte Quellen für diesen B-Lauf:** WFS-GeoJSON SHA-256 `5c7cba3a44491be4450e07630301d1f3d515a6a179c9e758372ed8484fd3a9e6`, OSM-Overpass-Rohdaten SHA-256 `23f6f2c944ab2d22cb9b974813dc391140be1dcc0822e6b65299620d17195696`, B-Kronen-GeoJSON SHA-256 `cf964d2561c2aeaa395881208e85f905379f930f59d4937370c17676b554a8e2`. Grundlage ist die dokumentierte Reihenfolge `wien_baumkataster > osm_tree > osm_tree_row`; OSM-Fallback **aktiv**.

**Interpretation und Grenzen:** Die vier zusätzlich relevanten Kronenkreise sind kein Beleg, dass nur vier nichtamtliche Bäume existieren. OSM kann unvollständig sein, Baumreihen fehlen in diesem Ausschnitt, und einer der vier Kreise beruht auf einem **frei angenommenen Höhenwert von 12 m**. Unterschiede zu C hängen außerdem an Geometriemodell und Erhebungszeitpunkt. **Mehr Überschirmung ist nicht automatisch bessere Genauigkeit.** Für eine quantitative Sensitivitätsprüfung empfiehlt sich als nächstes ein **getrennter B-Durchlauf mit `--strict-osm` in ein weiteres Ausgabeverzeichnis**; mit einem Orthofoto lassen sich die vier zusätzlichen Kronen direkt kontrollieren. Keine der früheren Referenzdateien von A oder C überschreiben.

## Variante C: Grünraummonitoring 2023 – WMS-Diagnose und Kronenprovider

**Datengrundlage:** Grünraummonitoring 2023 der Stadt Wien, Rasterbasis 50 cm, **Baumschicht als thematische Klasse 3**. Der WMS-Ebenenname ist **`GRM2023OGD`**, Dienst **`https://data.wien.gv.at/daten/wms`**. Die amtliche Methodik verwendet 2023er Sommer-Infrarotbilder und Höhendaten; diese Quelle unterscheidet sich grundlegend von der Kreisapproximation des Baumkatasters.

**Wichtig – Erhebungsjahr ≠ Layername ≠ Veröffentlichungsdatum (geprüft am 14.10.2026):**

| Datensatz / WMS-Layer | Amtlich dokumentierte Datenbasis | Luftbild-/Datengrundlage |
| --- | --- | --- |
| [Grünraummonitoring 2022 Wien](https://www.data.gv.at/datasets/684d2bbd-9bb7-319c-acb6-c1120e74e123?locale=de), `GRM2022OGD` | **2022** | Infrarot-Bildflüge am **15./18. Mai, 11. Juni und 13. Juli 2022**; FMZK Juli 2022; Höhenbasis aus Orthofoto 2019 |
| [Grünraummonitoring 2023 Wien](https://www.data.gv.at/datasets/ec7be5af-5b15-302a-9757-fb2a45181c8a?locale=de), **`GRM2023OGD` (unsere Quelle)** | **2023** | Infrarot-True-Orthofotos vom **14./18. Juli und 21./22. August 2023**; FMZK Juli 2023; ALS 2023 |

Die Stadt Wien nennt im [OGD-Changelog](https://digitales.wien.gv.at/changelog/) für beide Datensätze als Veröffentlichungsdatum im aktuellen Katalog den **22. Jänner 2026**. Es gibt also **nicht** einfach einen einzigen „2023 veröffentlichten Datenstand 2022“: Die Layer `GRM2022OGD` und `GRM2023OGD` sind unterschiedliche Datenprodukte. Für **die hier untersuchte braune Baumschicht** ist eindeutig `GRM2023OGD` im lokalen GetMap-Bericht verzeichnet; wir verwenden daher die **2023er** Befliegungen als Referenzzeitraum.

**Folge für die Bildinterpretation:** Ein Baum, der im aktuellen Baumkataster erscheint, aber in der GRM2023-Baumschicht fehlt, **könnte nach Sommer 2023** gepflanzt oder relevant gewachsen sein. Ebenso möglich sind Modellvereinfachung, versetzte Punkte, saisonale/zeitliche Unterschiede und Klassifikationsfehler. **Aus dem bloßen Layerunterschied lässt sich kein Pflanzdatum ableiten.** 


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

## Variante D: BEV Orthofoto RGBI – Quellenprüfung D1 (14.10.2026)

**Ziel:** Ein eigenständiges drittes Prinzip zur Kronengeometrie neben Stamm-Kreisnäherung (A/B) und GRM-Klassifikation (C). **Zunächst den bereits in der Kartensammlung verwendeten BEV-WMS** und die tatsächliche interne Übereinstimmung seiner dargestellten Kanäle untersuchen. Erst falls das für unsere Zwecke nicht ausreicht, Roh-RGBI-Multispektralraster beschaffen und prüfen.

### Vorrangiger erster Versuch: BEV-WMS aus der Kartensammlung (D0, implementiert)

**Korrektur des ursprünglichen D-Plans:** In der Kartensammlung gibt es bereits einen öffentlich eingebundenen BEV-Orthofoto-WMS. Der Erstversuch muss daher **keine riesigen RGBI-Kacheln herunterladen**. Die vorhandene Einbindung steht in [`Kartensammlung/src/app/basemaps/providers/imagery.js`](https://github.com/peter-alexander/Kartensammlung/blob/main/src/app/basemaps/providers/imagery.js) und nutzt `https://kataster.bev.gv.at/ortho/ows`. Sie enthält diese fünf Layer:

| Basemap | WMS-Layer | Laut Bezeichnung dargestellte Kanäle |
| --- | --- | --- |
| `bev_rgb` | `bev:RGB` | R / G / B |
| `bev_irgb` | `bev:IRGB` | NIR / R / G |
| `bev_rgir` | `bev:RGIR` | R / G / NIR |
| `bev_rirb` | `bev:RIRB` | R / NIR / B |
| `bev_ir` | `bev:IR` | NIR in Graustufen |

Das sind **fünf gerenderte Darstellungen**, kein garantiertes RGBI-Rohdatenraster. Aus den Namen ist die erwartete Kanalanordnung plausibel, die tatsächliche Gleichheit wird **erst gemessen**. Nicht mit den in der BEV-Dokumentation genannten **anmeldepflichtigen anderen Darstellungsdiensten** verwechseln; der konkrete Kataster-WMS-Endpunkt ist die in der Kartensammlung vorhandene Adresse.

**Neues, eigenständiges Diagnosemodul:** `scripts/probe_bev_wms.py`. Aufruf nach der Quellcode-Synchronisierung:

```bash
./scripts/update-and-sync.sh
.venv/bin/python -m scripts.probe_bev_wms
```

Das Skript verwendet dieselbe lokale FMZK-Testregion wie A/B/C und bezieht einmalig `GetCapabilities` (nur als Metadateninformation) plus fünf **direkte** `GetMap`-PNG-Bilder, **alle mit identischer BBOX, Projektion EPSG:3857, Rasterabmessungen und WMS-Version 1.3.0**. Standardmäßig wird ein etwa **0,5-m-Rastergitter** mit 15 m Umgebungspuffer angefragt, maximal 2.048 Pixel Kantenlänge und 3 Millionen Pixel/Bild. Der WMS kann intern neu sampeln; die Auflösung des Anfragegitters ist **keine zugesicherte BEV-Quellauflösung**.

Ausgabe unter `data/processed/baumkronen/bev_wms/`:

- `getcapabilities.xml`;
- `bev_rgb_test.png`, `bev_irgb_test.png`, `bev_rgir_test.png`, `bev_rirb_test.png`, `bev_ir_test.png`;
- für **jedes** Bild eine gleichnamige `.pgw`-Weltdatei und `.prj`-Projektionsdatei (EPSG:3857) zum GIS-Import;
- `bev_wms_diagnose.json` mit Rastergeometrie, WMS-Anfrage-URLs, SHA-256 pro Quelle, Alpha-/NoData-Sichtbarkeit und **pixelgenauem Vergleich mehrfach dargestellter Spektralkanäle**.

Ursprünglich wurde gefordert, dass der **Rotkanal** in RGB, IRGB, RGIR und RIRB sowie der **NIR-Kanal** in IRGB, RGIR, RIRB und IR übereinstimmt. Nach dem ersten echten Lauf unterscheidet die Diagnose einen **Kernkanaltest ohne die zusätzlichen, abweichenden IRGB-R/G-Darstellungen** von der weiterhin vollständigen Fehlerliste. Das Skript vergleicht auf **gemeinsam deckenden Pixeln** den Anteil exakt gleicher Pixel, den Anteil mit maximal 1 Grauwert Unterschied und den mittleren absoluten Unterschied. Es prüft auch die drei Farbkanäle der Graustufendarstellung gegeneinander. **Sonderfall BEV-WMS, beim ersten realen Lauf festgestellt:** `GetCapabilities` listet nur `bev:RGB`, während die Kartensammlung auch `bev:IRGB`, `bev:RGIR`, `bev:RIRB` und `bev:IR` erfolgreich per `GetMap` nutzt. Deshalb ist die **fehlende Deklaration kein Abbruchgrund** mehr: Die Diagnose protokolliert `nicht_in_capabilities` und für jedes Bild `in_capabilities` sowie `status: getmap_png_valide`. **Entscheidend ist die tatsächliche, gültige GetMap-PNG-Antwort in exakt angefragter Größe**. Ein XML-/Fehlertext statt PNG oder ein falsches Raster wird weiterhin abgelehnt und der betreffende Layer in der Fehlermeldung genannt. Bestehende Ausgaben werden ohne bewusstes `--overwrite` nicht ersetzt.

**Ganz wichtig:** Auch bei guter Übereinstimmung sind dies zunächst **gerenderte 8-bit-Werte** und *keine* nachgewiesenen linear-skalierenden, radiometrischen Rot-/NIR-Rohwerte. Ein daraus gerechneter Index dürfte zunächst höchstens **experimenteller WMS-Vegetationsindikator** heißen, nicht kalibrierter NDVI. Für die Kronentrennung brauchen wir darüber hinaus weitere Merkmale und idealerweise passende Höheninformationen.

**Erster echter BEV-Live-Test durchgeführt:** Der Anwender hat den WMS-Abruf mit fünf gültigen PNGs sowie den Diagnosebericht am 13./14.10.2026 nachgereicht; die Messwerte und die Einschränkung bei `IRGB` stehen im unmittelbar folgenden Abschnitt. Weitere Schritte sind für einen experimentellen WMS-Vegetationsindikator vorgesehen, nicht für einen bereits validierten NDVI. Das Bildmaterial bleibt lokal.

### Ergebnis des ersten echten WMS-Kanallaufs (13./14.10.2026)

Der erste lokale BEV-GetMap-Test war **erfolgreich**. Alle fünf PNGs wurden für denselben EPSG:3857-Rasterausschnitt erzeugt: **943 × 878 Pixel**, also **827.954** identisch positionierte Pixel, vollständig opak in allen fünf Darstellungen. Die WMS-Anfrage verwendete eine genäherte **0,5-m-Abtastung**; das bedeutet nicht, dass die darunterliegenden BEV-Quellpixel 0,5 m groß wären. Das tatsächliche Aufnahmejahr ist noch unbekannt.

**Messbericht:** `data/processed/baumkronen/bev_wms/bev_wms_diagnose.json` (13.10.2026, 23:31:16 UTC). Die GetMap-Bilder sind über die folgenden SHA-256-Hashes identifizierbar: `bev:RGB` `684fc4dcf312186b8887ee3022f79582d25ac9cee87428e8f46fc583a6f405ec`, `bev:IRGB` `130906dc2a78429c624f2ee2524940879200515bb56abcaaa2770b84734efdb3`, `bev:RGIR` `6c5ceb5dcf1b30143aaa0bb319e83058501edbe09b3d97d13d822cdbfc088978`, `bev:RIRB` `7be97636b94a3de6823c1ec011fa4f6bf92d60e826c7665228fcf0e1d7d946a5`, `bev:IR` `9ca9630eb3f06d0a96f6199f07d04952a2f12c6d20f5ab485162d749e752b1ca`.

| Kanalvergleich (jeweils an 827.954 gemeinsamen Pixeln) | Exakt gleich | Max. ±1 DN | Mittlere absolute Differenz |
| --- | ---: | ---: | ---: |
| R: `RGB.R` vs. `RGIR.R` und `RIRB.R` | **100 %** | **100 %** | **0 DN** |
| G: `RGB.G` vs. `RGIR.G` | **100 %** | **100 %** | **0 DN** |
| B: `RGB.B` vs. `RIRB.B` | **100 %** | **100 %** | **0 DN** |
| NIR: `IRGB.R` vs. `RGIR.B`, `RIRB.G`, `IR.R` | **100 %** | **100 %** | **0 DN** |
| IR-Graustufen: `IR.R` vs. `IR.G` und `IR.B` | **100 %** | **100 %** | **0 DN** |
| **R: `RGB.R` vs. `IRGB.G`** | 7,20 % | **20,58 %** | **8,394 DN** |
| **G: `RGB.G` vs. `IRGB.B`** | 5,17 % | **14,86 %** | **5,913 DN** |

**Interpretation:** Die pauschale Meldung `Kanalkonsistenz im WMS: NICHT bestanden` des ersten Diagnosecodes war für die beabsichtigte Vierkanalprobe **zu undifferenziert**. Lediglich die beiden R-/G-Kanäle von `IRGB` fallen durch; die **neun anderen Vergleiche sind auf jedem Pixel exakt**. Ob in `IRGB` eine andere Tonwertkurve, Farbbalance oder sonstige Darstellungslogik arbeitet, ist **nicht untersucht** und darf nicht behauptet werden.

**Konsequenz für D:** Für einen **experimentellen, unkalibrierten Bildkanalindex** kann vorläufig **R/G/B aus `bev:RGB`** und **NIR aus `bev:IR` (R-Kanal des Graustufen-PNGs)** verwendet werden. RGB.R und IR.R werden über RGIR/RIRB unabhängig wiederholt. `IRGB.G` und `IRGB.B` dürfen **nicht** als gleichwertige Rot-/Grünwerte für eine quantitative Berechnung ausgetauscht werden.

Der Prüfcode berechnet jetzt separat (a) `alle_kanalreplikate_intern_konsistent` – dieser Wert bleibt für den echten Lauf **false**, weil `IRGB` abweicht – und (b) **`kernkanaele_intern_konsistent`**, ausschließlich gestützt auf RGB / RGIR / RIRB / IR, **für den ersten Lauf true**. `abweichungen_alle_darstellungen` dokumentiert die beiden Abweichungen unverändert. Die neue Berechnung ist durch zwei zusätzliche Unit-Tests geprüft: ein IRGB-exklusiver Fehler beeinträchtigt die Kernkanalprüfung nicht; ein echter Fehler in einem Kernkanal wird weiterhin erkannt. **Das alte JSON enthält diese neuen Felder naturgemäß noch nicht**; die Bewertung ist hier aus den dokumentierten Einzelvergleichen abgeleitet.

**Fachliche Grenze:** Alle verglichenen Werte sind 8-bit-PNG-Darstellungswerte. Ihre exakte Reproduzierbarkeit macht aus ihnen noch keine **radiometrisch kalibrierten Reflexionsgrade**. Darum trägt die nun implementierte Vorstufe D2 ausdrücklich die Bezeichnung **experimenteller WMS-Vegetationsindex**, nicht wissenschaftlich belastbarer NDVI oder bestätigte Baumüberschirmung. Die visuelle Rasterprüfung und Unterscheidung von Baumkronen und bodennaher Vegetation stehen noch aus; Aufnahmejahr und etwaige Tonwertkurven bleiben offen.

### D2 – Experimentelle Vegetationserkennung ohne DSM/DTM (14.10.2026, implementiert)

**Bewusste Reihenfolge:** Wir erproben zuerst, wie gut sich Vegetation allein aus den bereits lokal gespeicherten BEV-WMS-Kanälen erkennen lässt. Höhenmodelle werden in D2 **nicht benötigt**. Da Grünflächen und Baumkronen spektral ähnlich aussehen können, wird **keine** Baumklassifikation und **keine** Überschirmungsquote behauptet.

**Neues eigenständiges Modul:** `scripts/analyze_bev_vegetation.py`. Es liest nur die vorhandenen `bev_rgb_test.png`, `bev_ir_test.png` und den alten oder neuen `bev_wms_diagnose.json`-Bericht, **ohne GetMap zu wiederholen**. Die Quell-PNGs werden anhand des Berichts per **SHA-256**, Pixelgröße, `.pgw`-Worldfile und `.prj`-Projektionsdatei geprüft. Für ältere Diagnosen ohne `kernkanaele_intern_konsistent` wird die Bestätigung anhand der tatsächlich im Bericht vorhandenen, einzeln dokumentierten R-/G-/B-/NIR-Vergleiche abgeleitet. Bei fehlender Kernkonsistenz wird abgebrochen; die bekannte Abweichung der zusätzlichen `IRGB`-Rot-/Grünkanäle bleibt dagegen unberührt.

Aus den gerenderten 8-bit-WMS-Werten werden pro Pixel Rot aus `bev:RGB.R` und NIR aus der `bev:IR.R`-Graustufendarstellung gelesen:

```text
I_WMS = (NIR_Anzeige - R_Anzeige) / (NIR_Anzeige + R_Anzeige)
```

Das ist **kein kalibrierter NDVI**; es werden weder radiometrische Rohdaten angenommen noch Werte aus `IRGB.G` oder `IRGB.B` eingesetzt. Pixel mit unvollständiger Deckung oder mit sehr schwachem `NIR+Rot` (Standard unter **20** 8-bit-Intensitätswerten) werden als *ungültig* behandelt, um vollständig dunkle/schattige Bereiche nicht durch eine Division durch nahezu null unbemerkt positiv einzustufen. Dies kann echte schattige Vegetation auslassen; der Ausschluss wird im Bericht gezählt.

**Standardvarianten:** Rein explorative Schwellwerte `0,10`, `0,20`, `0,30`, `0,40`. Sie sind **weder anhand von Referenzflächen optimiert noch vorgeschriebene NDVI-Grenzwerte**. Die Klassifikation bedeutet nur `I_WMS >= Schwelle`, unabhängig davon, ob die Vegetation aus einer Baumkrone, Wiese, Hecke oder Dachbegrünung stammt.

```bash
./scripts/update-and-sync.sh
.venv/bin/python -m scripts.analyze_bev_vegetation
```

**Ausgabeordner:** `data/processed/baumkronen/bev_vegetation/` – getrennt vom bisherigen `bev_wms/`-Quellverzeichnis, damit keine BEV-Bilder überschrieben werden.

- **`bev_vegetation_vergleich.png`**: das wichtigste Ergebnis für die erste visuelle Prüfung; Kontaktblatt mit RGB, IR, Index und vier grünen Kandidatenüberlagerungen. **Nicht georeferenziert**, weil mehrere Panels nebeneinander angeordnet sind.
- **`bev_vegetation_index.png/.pgw/.prj`**: georeferenzierter kontinuierlicher Index auf demselben EPSG:3857-WMS-Raster; Grauwert 0 = Index −1, 128 = 0, 255 = +1, ungültige Pixel transparent.
- **`bev_veg_maske_010/020/030/040.png/.pgw/.prj`**: georeferenzierte Binärmasken (Weiß = Indikator über Schwelle; Schwarz = unter Schwelle oder ungültig), keine Kronenpolygone.
- **`bev_veg_overlay_010/020/030/040.png/.pgw/.prj`**: georeferenzierte grüne Visualisierungen über dem Original-RGB-Bild, damit z. B. die Kartensammlung sie direkt anzeigen und transparent über andere Layer legen kann.
- **`bev_vegetation_bericht.json`**: Quelle mit SHA-256, Georeferenzierung, Kernkanal-Beleg, Anzahl gültiger/ungültiger Pixel, Treffer je Schwelle und deren Anteil am **gesamten Bildausschnitt** sowie den gültigen Pixeln.

**Wichtig zu den Prozenten:** Die Trefferanteile der vier Rastermasken beziehen sich auf die **gesamten 943 × 878 WMS-Bildpixel** bzw. gültigen Pixel – *nicht* auf den Straßenraum aus Modul 2 und schon gar nicht auf den offiziellen Begrünungs- oder Überschirmungsgrad. Es erfolgt **keine automatische Flächenmessung**, keine Interpolation, keine Polygonisierung und kein Vergleich der Prozente mit den bisherigen A/B/C-Werten.

**Optionale andere Schwellen**, falls die erste Vorschau zu wenig oder zu viel zeigt, ohne WMS-Neuabruf:

```bash
.venv/bin/python -m scripts.analyze_bev_vegetation \
	--thresholds 0.05,0.15,0.25,0.35 \
	--out-dir data/processed/baumkronen/bev_vegetation_versuch2
```

### Erster echter lokaler D2-Lauf – Vergleichsbild und Bericht geprüft (14.10.2026)

Der Nutzer hat `data/processed/baumkronen/bev_vegetation/bev_vegetation_vergleich.png` sowie `bev_vegetation_bericht.json` des lokalen Testausschnitts bereitgestellt. Die Berechnung wurde gegen die dokumentierten RGB-/IR-WMS-Prüfsummen validiert. Als Quellbeleg enthält der Bericht die Prüfsummen `684fc4dcf312186b8887ee3022f79582d25ac9cee87428e8f46fc583a6f405ec` (`bev:RGB`) und `9ca9630eb3f06d0a96f6199f07d04952a2f12c6d20f5ab485162d749e752b1ca` (`bev:IR`). Die ältere WMS-Kernkanalprüfung wurde aus den Einzelvergleichswerten rekonstruiert.

| Experimentelle Indexschwelle | Positive Rasterpixel | Anteil am gesamten WMS-Bild |
| --- | ---: | ---: |
| ≥ 0,10 | 125.345 | **15,14 %** |
| ≥ 0,20 | 100.521 | **12,14 %** |
| ≥ 0,30 | 73.720 | **8,90 %** |
| ≥ 0,40 | 37.915 | **4,58 %** |

**Alle 827.954 Rasterpixel** waren verwertbar. Der Bericht weist weder Transparenz noch ausgeschlossene, sehr dunkle Pixel auf (`min_signal=20`). Damit verändern sich die vier Trefferanteile ausschließlich durch die Indexschwelle. Die Werte sind **kein Begrünungs- oder Überschirmungsgrad**; innerhalb der WMS-BBOX sind auch Privatgrund, Innenhöfe und Dächer enthalten, außerdem der 15-m-Puffer.

**Vorläufige visuelle Bewertung des verkleinerten Kontaktblatts:**

- Baumreihen an Straßen und zahlreiche Einzelkronen werden in den Varianten **0,20 und 0,30** deutlich markiert; größere versiegelte Flächen bleiben überwiegend frei.
- **0,10** erkennt mehr schwächere Vegetationssignale, erhöht aber auch verstreute Markierungen auf schwer eindeutig einzuordnenden Flächen. Es ist aus dem Kontaktblatt allein nicht zu klären, ob diese Fehlklassifikationen darstellen.
- **0,40** entfernt viele Kandidaten und zerlegt einige größere Baum-/Vegetationsbestände in Teilbereiche. Es erscheint für eine vollständige Erfassung zu restriktiv, ist aber keine statistisch validierte Aussage über Recall.
- Die große begrünte Innenhoffläche im westlichen Teil und andere zusammenhängende Grünbereiche bleiben selbst bei höheren Schwellen überwiegend bzw. teilweise markiert. Das Verfahren **unterscheidet weder Baumkronen von bodennaher Vegetation noch hohe Sträucher von Bäumen**; daraus folgt noch kein Kronenpolygon.
- Schatten, Objektform und Mischpixel an Vegetationsrändern bleiben Unsicherheitsquellen. Ohne Pixel-Stichproben mit bestätigter Bodenwahrheit lassen sich weder Genauigkeit noch die beste Schwelle seriös bestimmen.

**Nächster überprüfbarer Schritt:** Kleine, nach Art getrennte Prüfflächen im Originalorthofoto markieren (z. B. sichere Baumkronen, Rasen/Beet, niedrige Sträucher, Dächer/Asphalt und schattige Kronen) und **die Indexwerte je Klasse** auswerten. Außerdem die Vegetationsmaske mit der vorhandenen Straßenraummaske überlagern, damit private Innenhofvegetation nicht die Diskussion über Straßenüberschirmung dominiert. Referenzkronen aus A/C können zum räumlichen **Vergleich** dienen, aber sie dürfen nicht unbemerkt als Trainings- oder Eingangsdaten für eine behauptete unabhängige Methode D verwendet werden. **Vorher keinen Schwellenwert als endgültige Kronenklassifikation festlegen.**

Die WMS-Quelldaten und die Programme A/B/C wurden bei dieser Dokumentation nicht verändert.

---

### D2-Feinvergleich und D3: Vorsichtige Kronenkandidaten ohne Höhenmodelle (14.10.2026)

**Entscheidung nach visuellem Feinvergleich D2:** Für die erste Erkennung bleibt **0,10** die vorläufige, möglichst vollständige Vegetations-Kandidatenschwelle. Der Wert **0,20** bleibt separat als Signal stärkerer Vegetation erhalten. Weder 0,17 noch 0,18 wird als scheinbar optimaler Trennwert festgelegt. Die Feinstudie mit identischen BEV-WMS-Quellbildern lieferte:

| WMS-Indexschwelle | Pixel über Schwelle | Bildanteil – ohne Straßenraumzuschnitt |
| --- | ---: | ---: |
| 0,10 | 125.345 | 15,14 % |
| 0,15 | 112.107 | 13,54 % |
| 0,17 | 107.448 | 12,98 % |
| 0,18 | 105.124 | 12,70 % |
| 0,20 | 100.521 | 12,14 % |

Bei 0,10 sind damit gegenüber 0,20 **24.824 zusätzliche Rasterpixel** erfasst (24,7 % mehr Kandidatenpixel relativ zur 0,20-Ausgabe). Das sind ausdrücklich **keine** zusätzlich bestätigten Baumkronen oder Vegetationsflächen des öffentlichen Straßenraums. Die Bildwerte sind keine radiometrisch kalibrierten NDVI-Messwerte.

**Neue, getrennte Teststufe D3:** `scripts/segment_bev_vegetation.py` arbeitet rein lokal mit den bereits geprüften BEV-`RGB`- und `IR`-PNGs samt SHA-256- und Georeferenzierungsprüfung. Die bisherigen D2-Dateien und die Referenzmethoden A/B/C werden nicht verändert.

1. Mit `I_WMS >= 0,10` entsteht eine großzügige Vegetationsmaske.
2. Pixel mit `I_WMS >= 0,20` bilden stärkere Signale. In der **achtfach verbundenen** 0,10-Maske werden zusammenhängende Regionen gebildet; Regionen **ohne** mindestens einen 0,20-Pixel bleiben als schwache Vegetation dokumentiert und werden **nicht** in die Hysterese-Kandidaten übernommen.
3. Pro Region werden Pixelzahl, Pixel-Bounding-Box, Füllgrad, Seitenverhältnis, ein rein indikatives Kompaktheitsmaß, Anteil der 0,20-Kernpixel und die **mittlere RGB-Luminanzdifferenz zwischen internen Nachbarpixeln** berechnet.
4. Für einen **explorativen**, noch **nicht** an Referenzbeispielen kalibrierten Test bekommen große Regionen mit mittlerer Nachbartextur ab **8 Grauwerten (DN)** die Bezeichnung `strukturreicher_kronenkandidat`. Sehr gleichmäßige Regionen bis **4 DN** bleiben `strukturarm_nicht_als_baum_ausgeschlossen`; andere Objekte `unklare_vegetation`. Regionen mit weniger als **12 Pixeln** werden als `klein_unklar` geführt. Die genauen Schwellen sind CLI-Parameter und gelten **nicht** als Qualitätsnachweis.

**Grenze der Hysterese:** Eine Baumkrone kann an eine Wiese oder Hecke anschließen und dadurch in **derselben** Komponente landen; Textur und Form gelten dann für die *Mischfläche*. Umgekehrt darf das Fehlen eines 0,20-Kerns nicht automatisch als `keine Vegetation` interpretiert werden. Auch die Strukturarm-Klasse bedeutet ausdrücklich **nicht**, dass es sich sicher um Rasen und nicht um einen Baum handelt. Die Farbcodierung ist eine vorläufige menschliche Prüfhilfe und **kein** validiertes Baumkronenmodell.

**Lokal ausführen:**

```bash
./scripts/update-and-sync.sh
.venv/bin/python -m scripts.segment_bev_vegetation
```

Quellen unter `data/processed/baumkronen/bev_wms/`, neue und getrennte Ergebnisse standardmäßig unter `data/processed/baumkronen/bev_segmentierung/`:

| Ausgabe | Inhalt |
| --- | --- |
| `bev_segmentation_kandidaten.png` | RGB-Orthofoto mit halbtransparenten **Objektklassen** (grün = strukturreiche Kronenkandidaten, blau = strukturarme Vegetation, gelb = unklar/klein, grau = schwaches Signal ohne 0,20-Kern) |
| `bev_segmentation_klassen.png` | Dasselbe Raster als farbige Klassen ohne RGB-Untergrund |
| `bev_segmentation_kronenkandidaten.png` | Binärmaske **nur der strukturreichen Kronenkandidaten** – noch keine bestätigte Überschirmung |
| `bev_segmentation_hysterese.png` | Binärmaske der 0,10-Komponenten, die mindestens einen 0,20-Kern enthalten, unabhängig von RGB-Textur |
| `bev_segmentation_objekte.json` | Alle zusammenhängenden Objekte mit Pixelkoordinaten und Form-/Textur-/Kernstatistik; **kein GeoJSON** |
| `bev_segmentation_bericht.json` | WMS-Herkunft, Prüfsummen, Schwellwerte, Klassen-Bilanzen, Qualitätsgrenzen und Ausgaben |

Die vier PNGs sind jeweils als `PNG/.pgw/.prj` in **EPSG:3857** abgelegt und können für eine direkte visuelle GIS-Prüfung verwendet werden. Die Klassenmaske darf nicht allein aufgrund ihrer Farbe mit `measure_canopy_cover.py` als amtlicher Überschirmungsgrad gemessen werden. Der Bildausschnitt enthält auch private Innenhöfe und Dächer.

**Validierung vor Kronenpolygonen:** Zunächst den tatsächlichen D3-Bildbericht und die Klassenübersicht kontrollieren, insbesondere strukturreiche **Wiesen** (Falschpositiv), glatte **Kronen** (Falschnegativ), Schatten, zusammenhängende Baum-/Rasenbereiche und lange Straßenbaumreihen. Im zweiten Schritt unabhängige Positiv-/Negativflächen aus dem Orthofoto anlegen, um Textur- und Formregeln zu prüfen. A/B/C können danach unabhängige Vergleichsflächen liefern, dürfen aber nicht unbemerkt die D3-Kronenerkennung steuern. **Für Methode D wird weiterhin keine neue Überschirmungsquote angegeben.**

---

### Tatsächlicher lokaler D3-Befund – 14.10.2026

**Datengrundlage:** Vom Benutzer bereitgestelltes `bev_segmentation_kandidaten.png` und `bev_segmentation_bericht.json`; der Bericht stammt aus der getrennten D3-Implementierung mit `low=0,10`, `strong=0,20`, `min_signal=20`, `strukturreich_ab=8 DN`, `strukturarm_bis=4 DN`, `klein_unter=12 Pixel`. Das Quellraster besitzt 943 × 878 = **827.954** gültige Pixel. Quellbild-Prüfsummen stimmen mit den zuvor dokumentierten BEV-WMS-RGB/IR-Darstellungen überein.

| D3-Klasse | 8fach zusammenhängende Komponenten | Pixel | Anteil an allen 125.345 Vegetationspixeln (≥ 0,10) |
| --- | ---: | ---: | ---: |
| Strukturreiche *Kronenkandidaten* (grün) | **233** | **104.483** | **83,36 %** |
| Unklare Vegetation (gelb) | **19** | **17.894** | **14,28 %** |
| Vegetation ohne ≥ 0,20-Kern (grau) | **664** | **2.046** | **1,63 %** |
| Strukturarme Vegetation (blau) | **13** | **675** | **0,54 %** |
| Kleine unklare Objekte | **37** | **247** | **0,20 %** |
| **Insgesamt** | **966** | **125.345** | **100 %** |

Die stärkere 0,20-Maske umfasst **100.521 Pixel**. Die Hysterese behält **123.299 Pixel bzw. 98,37 %** der 0,10-Maske: Nur 1,63 % der Vegetationskandidaten gehören zu zusammenhängenden Komponenten ohne einen einzigen stärkeren Kern. **Das 0,20-Kernkriterium ist für das Entfernen ganzer Vegetationsobjekte damit kaum selektiv**. Die größte 0,10-Komponente umfasst **18.828 Pixel**, also weit mehr als eine typische kleine Einzelbaumkrone. Solche zusammenhängenden Flächen können Bäume, Rasen und Beete gemeinsam enthalten.

**Beobachtungen anhand des Bildes, noch ohne unabhängige Referenzklassifikation:**

- Die erkannten grünen Straßenbaumkronen/-reihen und viele Innenhofbereiche bestätigen, dass **0,10 als Vegetations-Kandidatenschwelle** brauchbar erscheint.
- Lange gelb markierte zusammenhängende Streifen entlang von Straßen – auffällig im rechten oberen und linken unteren Bildbereich – sehen im zugrundeliegenden Orthofoto **stark nach Straßenbaumreihen** aus. Sie landen trotz sichtbarer Kronenstrukturen teilweise in `unklare_vegetation`; also mögliche *falsch negative Kronenklassifikationen*.
- Die große grüne Fläche im westlichen Innenhof wirkt wie **gemischte Vegetation**: Einzelne Bäume und bodennahe Vegetation können zusammenhängen. Die vollständige grüne Klassifizierung ist **kein Nachweis**, dass diese gesamte Fläche von Baumkronen bedeckt ist; mögliche *falsch positive Kronenklassifikationen*.
- Der bisherige Algorithmus **berechnet** je zusammenhängendem Objekt Bounding-Box-Füllgrad, Seitenverhältnis und Kompaktheit, **verwendet diese Werte aber noch nicht für die Klassenentscheidung**. Die grüne Klasse entsteht im Wesentlichen aus dem mittleren RGB-Luminanzkontrast im **gesamten** Objekt (≥ 8 DN), sofern Größe und starker Kern vorhanden sind. Schon deshalb kann ein großes Mischobjekt als einheitliche „Krone“ erscheinen.

**Fachliches Urteil:** Der D3-Lauf bestätigt den Nutzen der spektralen Vegetationsmaske, **nicht** die Zuverlässigkeit der Textur-Kronenerkennung. Die 104.483 grünen Pixel (= 83,36 % der Kandidaten) dürfen **nicht** als erkannte Baumkronen, Überschirmungsgrad oder validierte Methode D berichtet werden. Ein objektweiter Textur-Grenzwert kann die Baum-/Rasen-Grenze nicht zuverlässig ziehen. Auch der reine 0,20-Kernfilter trennt kaum.

**Empfohlener nächster Schritt (noch nicht implementiert):** Zuerst einige **manuell bestätigte** Beispielbereiche markieren: deutliche Straßenbaumkronen (einschließlich der gelben Reihen), gemischter Innenhof, zusammenhängender Rasen, Hecken/Beete, Schatten und Dachflächen. Danach den Verlauf **lokaler** RGB-Textur in Fenstern (z. B. 5×5/9×9 Pixel) sowie den kontinuierlichen spektralen Index gegen diese Beispielflächen vergleichen und eine Unterteilung großer Vegetationskomponenten prüfen. Die volle 0,10-Maske und das 0,20-Signal bleiben unabhängig erhalten; echte Kronenpolygone und eine Straßenraumquote bleiben zurückgestellt. Der Objektbericht `bev_segmentation_objekte.json` ist noch nicht hier ausgewertet und wäre für weitere größen-/formabhängige Diagnosen nützlich.

---

### Zwischenmessung D2/D3: alle D-Varianten auf identischem Straßenraum (14.10.2026)

**Motivation:** Vor weiteren Versuchen mit Texturschwellen und lokaler Segmentierung wollen wir erstmals wissen, welche **Flächenanteile im tatsächlichen Straßenraum** die bereits vorhandenen D-Varianten ergeben. Die bisherigen 12–15 % aus D2 bezogen sich **auf das gesamte Orthofoto einschließlich privater Innenhöfe und Dächer** und sind nicht mit A/B/C vergleichbar.

**Neues Skript:** `scripts/compare_bev_variants.py`. Verwendet nur lokal vorhandene Dateien; **kein zusätzlicher WMS-Download, keine Anpassung an den D-Algorithmen**:

- Quellbilder `data/processed/baumkronen/bev_wms/bev_rgb_test.png` / `bev_ir_test.png`, anhand der WMS-Diagnose (SHA-256, `.pgw/.prj`) geprüft.
- Vorläufiger Straßenraum `data/processed/street_space/fmzk_strassenraum.geojson` und `data/processed/fmzk_test.gpkg` über **denselben Modul-2-Adapter** wie A/B/C.
- Die **sieben bisher tatsächlich geprüften D2-Schwellen** `0,10`, `0,15`, `0,17`, `0,18`, `0,20`, `0,30`, `0,40`.
- Die bisherige unveränderte D3-Objektklassifikation: `Hysterese (0,10 mit 0,20-Kern)`, `strukturreiche Kronenkandidaten`, `Kronenkandidaten + unklare Vegetation` und die fünf Einzelklassen. Ein vorhandener `bev_segmentation_bericht.json` wird gegen die neu berechneten Klassenhäufigkeiten, Parameter und Quellbild-Prüfsummen kontrolliert, damit tatsächlich **derselbe D3-Lauf** verglichen wird.
- Die bestehenden Kronengeometrien A/B/C werden zur direkten Gegenüberstellung eingelesen, **wenn sie lokal vorhanden sind**; fehlende Referenzen werden ausdrücklich als fehlend dokumentiert. Zusätzlich wird die räumliche Überlappung **aller sieben D2-Schwellen** sowie der drei ausgewählten D3-Varianten mit jeder verfügbaren Referenz A/B/C (IoU) gemessen. Der JSON-Bericht enthält `raeumliche_vergleiche` (bis zu 30 Werte), die Konsole die vollständige D2-IoU-Tabelle samt maximalem IoU je Referenz. **IoU misst Übereinstimmung, keine Genauigkeit der Baumkronenerkennung**.

**Metrische Berechnung:** Die Binärmasken werden **im originalen georeferenzierten WMS-Raster EPSG:3857** als Rasterzell-Rechtecke bzw. zusammenhängende horizontale Streifen polygonisiert, geometrisch vereinigt und nach EPSG:31256 transformiert. Der Schnitt erfolgt **geometrisch** mit der bestehenden Straßenraum-Polygonmaske. Damit werden teilweise bedeckte **Randpixel anteilig** berücksichtigt, statt einen Pixel allein aufgrund seines Mittelpunkts vollständig hinzuzuzählen. Die Straßenraumfläche bleibt der gemeinsame, aus Modul 2 übernommene Nenner; die Ausgabe wird verweigert, wenn der WMS-Ausschnitt den Straßenraum nicht vollständig umfasst. Reprojektion und Abtastraster bleiben trotzdem eigene Auflösungs-/Rasterisierungsunsicherheiten.

**Ein einziger Offline-Aufruf:**

```bash
./scripts/update-and-sync.sh
.venv/bin/python -m scripts.compare_bev_variants
```

Ergebnis: `data/processed/baumkronen/bev_variantenvergleich/bev_varianten_strassenraum_vergleich.json` sowie eine **Konsolentabelle** mit m² und Prozentwerten für sämtliche D2/D3-Varianten und – sofern die Quell-GeoJSONs vorhanden sind – A/B/C.

**Wichtig für die Interpretation:** Die neue Vergleichsrechnung erzeugt **deskriptive Flächenanteile von D-Masken im Straßenraum**. Die D2-Masken enthalten auch Rasen und Sträucher, die D3-Kronenkandidaten können große Innenhof-Mischflächen umfassen beziehungsweise Straßenbaumreihen übersehen. Der Zahlenwert einer solchen Maske **ist noch keine gültige Messung des Wien-Plan-Überschirmungsgrads**. Erst die gemessenen D-Quoten betrachten, danach entscheiden, ob eine verfeinerte Segmentierung überhaupt nötig oder sinnvoll ist. A/B/C werden nicht verändert oder überschrieben.

**Stand (14.10.2026):** Der ursprüngliche Actions-Lauf [#38491355200](https://github.com/peter-alexander/ks-Gartenstrassen/actions/runs/38491355200) scheiterte an zwei Testannahmen (erwarteter Text einer Fehlermeldung und zu strenge IoU-Toleranz eines kleinen rückprojizierten Testpolygons). Der Nachfolgelauf [#38491420024](https://github.com/peter-alexander/ks-Gartenstrassen/actions/runs/38491420024) war erfolgreich. Die beiden Testkorrekturen änderten weder das D-Verfahren noch die Straßenraumgeometrie.

**Performanceprüfung:** Der Vergleich protokolliert nun die Laufzeit seiner fünf Phasen unter `zeitmessung` sowie die Laufzeit jeder einzelnen D-Variante unter `varianten[*].laufzeit_s`. Für einen aussagekräftigen Leistungsbefund ist der Lauf mit den originalen Pixelmasken nötig. Eine synthetische lokale Einzelmessung mit 943 × 878 Pixeln und 14.196 horizontalen Pixelruns benötigte ungefähr 0,55 s für die geometrische Vereinigung und 0,15 s für die Projektion; das ist **kein** Messwert des realen D-Vergleichs. Bei einer auffälligen Laufzeit zuerst die D-Phasen und Run-Anzahlen kontrollieren, bevor man die anteilige Randzellenbehandlung optimiert.

**Realer Lauf am 14.10.2026:** Die lokal erzeugte und zur Auswertung bereitgestellte `bev_varianten_strassenraum_vergleich.json` enthält alle 14 D-Masken auf **46.630,56 m² Straßenraum**, reproduzierte D3-Quelldaten und bei allen Polygonisierungen den Status `valide`, also **keine Geometriereparatur**. Gesamtlaufzeit **6,41 s**, davon **4,66 s** für die 14 Masken und **0,62 s** für 15 räumliche Vergleiche. Die WMS-Bilddateien und das FMZK liegen weiterhin nur lokal, nicht im Git-Repository.

| D2-Schwelle | Vegetationsmaske im Straßenraum | Anteil |
| --- | ---: | ---: |
| 0,10 | 5.715,52 m² | 12,26 % |
| 0,15 | 5.325,46 m² | 11,42 % |
| 0,17 | 5.168,97 m² | 11,08 % |
| 0,18 | 5.085,39 m² | 10,91 % |
| 0,20 | 4.932,71 m² | 10,58 % |
| 0,30 | 3.875,68 m² | 8,31 % |
| 0,40 | 2.417,44 m² | 5,18 % |

**Referenzflächen:** A = 3.647,05 m² (7,82 %), B = 3.678,65 m² (7,89 %), C = 4.358,69 m² (9,35 %). Von den zuvor gemessenen D2-IoUs lagen 0,20 gegen alle drei Referenzen vor 0,10: A 58,82 % statt 57,17 %, B 58,52 % statt 57,05 %, C 70,99 % statt 68,51 %. Für die fünf anderen D2-Schwellen lagen im ersten Bericht noch keine räumlichen IoUs vor. Ein ähnlicher Flächenanteil allein bedeutet nicht höhere Übereinstimmung; ebenso ist IoU gegen A/B/C keine unabhängig validierte Klassifikationsgenauigkeit.

**Nächster lokaler Schritt (erweiterter D2-IoU-Vergleich):** Im aktualisierten Repository mit unveränderten lokalen Quelldateien erneut ausführen. Da der erste Bericht bereits existiert, **neues Ausgabeverzeichnis wählen**, damit nichts überschrieben wird:

```bash
git pull --ff-only
.venv/bin/python -m scripts.compare_bev_variants \
	--out-dir data/processed/baumkronen/bev_variantenvergleich_iou_alle_d2
```

Die neue Datei `bev_variantenvergleich_iou_alle_d2/bev_varianten_strassenraum_vergleich.json` enthält bei verfügbaren A/B/C-Geometrien **21 D2- und 9 D3-IoUs**. Eine WMS-Neuabfrage oder Änderung der bestehenden Schwellen/Klassen ist dafür nicht erforderlich. Erst anhand dieser Daten die sieben D2-Schwellen räumlich vergleichen; die fehlenden IoUs können aus den aggregierten Flächen des ersten JSON-Berichts **nicht** rückwirkend berechnet werden.

---

**Wenn die WMS-Qualität unzureichend ist**, bleibt der eigenständige Roh-RGBI-Adapter `scripts/probe_bev_rgbir.py` als zweite Quelle erhalten. Ein großer TIFF-Download ist erst gerechtfertigt, wenn die WMS-Ergebnisse keine ausreichend verlässliche Spektraldiagnose zulassen.

---

### Amtlich bestätigte Daten und Bezugswege

- [BEV – Orthophoto Farbe](https://www.bev.gv.at/Services/Produkte/Luftbildprodukte/Orthophoto-Farbe.html): Seit 2010 digitale Orthophotos mit rund **20 cm** Pixelgröße; Produkte in RGB, CIR (Falschfarbeninfrarot) und RGBI. **RGBI umfasst Rot, Grün, Blau und einen separaten Nahinfrarotkanal**; erhältlich als TIFF/GeoTIFF. Das BEV nennt ein kostenloses Angebot `Digitales Orthophoto Farbe und Infrarot (DOP RGBI) Operat` unter [data.bev.gv.at](https://data.bev.gv.at/), jedoch standardmäßig als **50 × 50-km-Kacheln**. Das kann bei 20 cm Auflösung sehr große Dateien bedeuten; **vor dem Herunterladen Größe und Wien-Abdeckung prüfen**.
- [BEV – Aktualitätsübersichten RGBI, Stand 15.04.2026](https://www.bev.gv.at/Services/Downloads/Produktbezogene-Downloads/Uebersichten.html): Zu jedem Aufnahmegebiet muss das **tatsächliche Bildflugjahr** geprüft werden. `aktuell` bezeichnet nicht zwingend 2025 oder 2026.
- Nach den [offiziellen, in der EU-Datensammlung indexierten Operat-Metadaten](https://data.europa.eu/data/datasets/34490301-7c3e-40b4-8cb8-e82e5c304e8e~~1) liefert das BEV manche Operate als **getrennte TIFF-Datensätze für RGB und NIR**, nicht immer als ein einziges vierbandiges TIFF. Der Probe-Adapter berücksichtigt deshalb beide Fälle.
- [BEV – Darstellungsdienst](https://www.bev.gv.at/Services/Geoinformationsdienste/BEV-Geodatendienste/BEV-Darstellungsdienst.html): WMS-Darstellungsdienst für digitale Orthofotos ist **nicht anonym zugänglich**, sondern benötigt Registrierung und Token. Zudem sind dargestellte Bilder **keine Garantie für unveränderte Rot-/NIR-Messkanäle**.
- [Wiener Orthofoto 2025](https://www.wien.gv.at/stadtplanung/orthofoto-daten-beziehen) und [basemap.at Orthofoto (Datenstand Flug 2025)](https://basemap.at/release-infos/) dienen uns ggf. als **aktuellere optische Referenz**, dürfen aber **nicht** ohne Nachweis eines echten NIR-Kanals als BEV-RGBI-Ersatz in ein NDVI-Verfahren eingehen.

### Phase D1 – Rohdatei technisch diagnostizieren (implementiert)

Eigenständiger Prüfbaustein `scripts/probe_bev_rgbir.py`. Er liest einen **lokal bereitgestellten** BEV-Rasterdatensatz per `gdalinfo -json` und protokolliert:

- Georeferenzierung (CRS/EPSG, Pixelgröße, Geotransformation und tatsächlich abgedecktes Gebiet);
- Anzahl, Typ, Interpretation und NoData-Kennung der Rasterbänder; **keine automatische Annahme, Band 4 sei NIR**;
- optional tatsächliches Aufnahmejahr, nur aus **zugehörigen BEV-Metadaten**;
- optional `--clip`: nur denselben gepufferten FMZK-Testausschnitt auslesen, EPSG:31256, 20-cm-Anfragegitter, ohne Änderungen an A/B/C. Der GDAL-Zuschnitt mit `-r near` ist ein Prüfraster und kann neu ausgerichtete Rasterzellen enthalten.

**Variante 1: TIFF mit vier Bändern:**

```bash
./scripts/update-and-sync.sh

# Zuerst nur Metadaten ansehen, ohne das große Raster zu schneiden
.venv/bin/python -m scripts.probe_bev_rgbir \
	--input /pfad/zur/BEV_RGBI_Quelle.tif

# Danach erst, wenn die Quelle den Testausschnitt vollständig enthält
.venv/bin/python -m scripts.probe_bev_rgbir \
	--input /pfad/zur/BEV_RGBI_Quelle.tif \
	--clip
```

**Variante 2: RGB und NIR als separate TIFF-Dateien:**

```bash
.venv/bin/python -m scripts.probe_bev_rgbir \
	--input /pfad/zur/BEV_RGB.tif \
	--nir-input /pfad/zur/BEV_NIR.tif \
	--clip
```

Das Skript verlangt mindestens `gdalinfo` und für `--clip` auch `gdalwarp` (`sudo apt install gdal-bin`). Fehlt bei TIFF + Worldfile der eingebettete Projektionseintrag, nur nach manueller Prüfung `--source-crs EPSG:31256` ergänzen. `--acquisition-year 2025` darf **ausschließlich** verwendet werden, wenn die BEV-Quelldokumentation für die konkrete Rasterdatei tatsächlich 2025 bestätigt.

Ausgaben unter `data/processed/baumkronen/bev_rgbir/`:

- `bev_rgbir_diagnose.json` – Quelldatei, Pixelgrößen/CRS/Bandbeschreibung, Metadaten, vollständige BBOX-Prüfung, ausgewiesene Unsicherheiten;
- beim vierbandigen `--clip` **`bev_rgbir_testausschnitt.tif`**; bei getrennten Quellen **`bev_rgb_testausschnitt.tif`** und **`bev_nir_testausschnitt.tif`** mit gemeinsamer exakt kontrollierter Rastergeometrie.

**Keine Kronenpolygone und kein Überschirmungsgrad werden in D1 erzeugt.** Die Rohdaten bleiben lokal unter `data/` bzw. außerhalb des Git-Repositories. Das Skript lädt keine 50-km-Kacheln automatisch herunter, manipuliert keine BEV-Originaldatei und verweigert eine nicht vollständig abgedeckte Testregion.

### Geplanter fachlicher Ablauf D2–D4 (noch nicht implementiert)

**D2 – Spektrale Prüfung:** Datenherkunft, Bandreihenfolge, Lagebezug und gültige Pixel eindeutig bestätigen; NDVI als Vegetationsindikator aus realen **NIR-/Rot-Kanälen** prüfen, ohne bereits „NDVI = Baum“ zu setzen. Sonderfälle: Schatten, Fassaden-/Dachvegetation, Wasser, nicht belaubte Bäume.

**D3 – Baumkronen von anderer Vegetation trennen:** z. B. mit `nDSM = DOM - DGM` (Höhe über Boden), Textur/Objektform, gegebenenfalls Wiener Baumstandorte als Validierung. Untersuchen, welches Oberflächen-/Geländemodell **zeitlich** zum BEV-Bildflug passt. Alle Schwellwerte und Erkennungsfehler offen dokumentieren.

**D4 – Eigener Polygonprovider:** Erst nach geprüfter D2/D3-Klassifizierung wird ein Kronen-GeoJSON (EPSG:4326, Polygon/MultiPolygon) erzeugt und **unverändert** mit `measure_canopy_cover.py` und `compare_canopy_methods.py` gemessen. A/B/C bleiben getrennte Referenzen.

**Offener Punkt vor dem ersten lokalen D1-Lauf:** Ein tatsächlich für den Wiener FMZK-Testausschnitt geeignetes RGBI-BEV-Raster (entweder 4 Bänder oder RGB-/NIR-Dateipaar) muss erst lokal beschafft oder als kleiner, unverändert mehrkanaliger Ausschnitt bereitgestellt werden. Ein vollständiger 50×50-km-Download ist nicht zwingend der wirtschaftlichste Weg; wir müssen die Lieferoptionen für kleine Ausschnitte abwägen.

## Langfristige Modularität

Alle Kronenprovider sollen dieselbe **Kronen-Geometrieschnittstelle v1** bedienen: GeoJSON FeatureCollection, Polygon/MultiPolygon, EPSG:4326; Attribute optional. Modul 4 (Messung) importiert keinen der Provider. Die Straßenraum-Eingabe bleibt die bereits in [Modulare Architektur](Modulare-Architektur.md) vereinbarte Schnittstelle von Modul 2.

Das Vergleichsmodul berichtet bewusst **Unterschiede**, nicht „der beste Ansatz“. Ohne unabhängige Referenzflächen (z. B. manuell geprüfte Kronenumrisse über Sommerorthofotos) kann kein Verfahren allein auf Basis einer größeren Überschirmungsquote als genauer bezeichnet werden. Beim Wechsel des Standardproviders und bei Änderungen an der Straßenraum-Maske Vergleichsversion und SHA-256 erhalten.

Quellinformationen: [Stadt Wien – Baumkataster](https://www.wien.gv.at/umwelt/stadtbaeume); [Grünraummonitoring 2023 – amtliche Metadaten](https://www.data.gv.at/datasets/ec7be5af-5b15-302a-9757-fb2a45181c8a?locale=de); [Grünraummonitoring 2022 – amtliche Metadaten](https://www.data.gv.at/datasets/684d2bbd-9bb7-319c-acb6-c1120e74e123?locale=de); [Stadt Wien – OGD-Changelog](https://digitales.wien.gv.at/changelog/); [BEV – Orthophoto Farbe](https://www.bev.gv.at/Services/Produkte/Luftbildprodukte/Orthophoto-Farbe.html).
