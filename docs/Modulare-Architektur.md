# Modulare Architektur – Wiener Gartenstraßen

**Stand 13.10.2026.** Das Projekt wird in unabhängigen Verarbeitungsschritten aufgebaut. Insbesondere darf der Austausch der Straßenraum-Abgrenzung **keine Änderung an den Kennzahlenmodulen** erfordern. Die erste Methode (FMZK + BEV-Kataster) bleibt als austauschbare Implementierung von Modul 2 erhalten und gilt weiterhin als **vorläufig**.

## Übersicht

```text
Modul 1: Datenbeschaffung, Zuschnitt und Validierung
   ├─ FMZK (GeoPackage, EPSG:31256)
   └─ Kataster (gst/nfl, BEV-Z16-Vektorkacheln; optionale Details)
                  │
                  ▼
Modul 2: Straßenraum ermitteln – Implementierung austauschbar
   Aktuell: FMZK-Kern + Kataster-nfl (95/65), vollständige FMZK-Polygone
                  │
                  ▼
      STANDARD-SCHNITTSTELLE: Straßenraum-GeoJSON (Polygone, EPSG:4326)
                  │
      ┌───────────┼──────────────────────┐
      ▼           ▼                      ▼
Modul 3        Modul 4              weitere Module
Bodenbegrünung Überschirmung        z.B. Versiegelung, Aufenthaltsqualität
      │           │                      │
      └───────────┼──────────────────────┘
                  ▼
       Spätere Kombination und Auswertung pro Straßenabschnitt
```

Die Module 3, 4 usw. beziehen ihre **Bezugsgeometrie** aus der gemeinsamen Straßenraum-Schnittstelle. Sie dürfen **nicht** voraussetzen, dass die Straßenraum-Objekte FMZK-Klassen, Kataster-KG/Grundstücksnummern oder spezifische Zuordnungsgründe enthalten.

## 1. Datenbeschaffung und Vorbereitung

**Aktuelle Bausteine:** `scripts/extract_fmzk.py`, `scripts/fmzk_source.py`, `scripts/analyze_kataster.py`.

- FMZK als lokale Originalquelle (`FMZK_WIEN_GP.gpkg`), Test-Extraktion nach `data/processed/fmzk_test.gpkg` (Layer `fmzk`, EPSG:31256) und Extraktionsmanifest `data/processed/fmzk_test.json`.
- BEV-Vektorkacheln `gst` (Grundstücke) und `nfl` (Nutzungsflächen), derzeit Zoomstufe 16; nur benötigter Ausschnitt mit Cache, getrennt von FMZK.
- Zusätzliche Grundstücks-API `/api/gst/<kgez>/<gnr>/` ist **optional**, da zeitweise nicht verfügbar. Fehlende Daten dürfen nicht in „nur Verkehr“ umgedeutet werden.
- Der gemeinsame, **rein lesende FMZK-Adapter** `scripts/fmzk_source.py` prüft Metadaten, Geometrien, CRS, Zuschnitt und Feature-Anzahl. Er gehört zu keinem fachlichen Straßenraum-Algorithmus.

**Grenze:** Datenbeschaffung und Dateiformate sind noch auf den kleinen lokalen Testausschnitt ausgelegt. Wienweite Verarbeitung kommt später.

## 2. Straßenraumgeometrie – austauschbare Erzeugung

**Aktuelle Implementierung:** `scripts/analyze_street_space.py`, `scripts/analyze_kataster.py`, `scripts/export_fmzk_strassenraum.py`.

Sie verbindet die FMZK-Kernklassen **21/23/24/33/39** mit der räumlichen Lage anderer FMZK-Polygone innerhalb der BEV-`nfl`-Nutzungen **95/65**. Die aktuell verwendete Schwelle beträgt 95 % Straßenmasken-Deckung und höchstens 5 % Überdeckung mit anderen Nutzungen. **Die Grenzen und offenen Fehlerfälle sind getrennt dokumentiert**: [Methodik FMZK/Kataster](Methodik-Strassenraum-FMZK-Kataster.md).

### Stabiler Übergabevertrag von Modul 2 zu den Kennzahlenmodulen (v1)

| Eigenschaft | Anforderung |
| --- | --- |
| Format | GeoJSON `FeatureCollection`, mit mindestens einem Polygon-`Feature` |
| Geometrietyp | `Polygon` oder `MultiPolygon`; alle Flächen werden für Berechnungen geometrisch vereinigt |
| Koordinaten | **EPSG:4326**, Koordinatenfolge `[Längengrad, Breitengrad]` gemäß GeoJSON |
| Ausdehnung | Derselbe Testausschnitt wie das dazugehörige FMZK-GeoPackage; kein stilles Abschneiden einer anderen Region |
| Attribute | **Nicht erforderlich**. `properties` können beliebig oder leer sein |
| Bedeutung | Vorläufig als Straßenraum betrachtete Boden-Bezugsfläche; keine rechtliche Feststellung |
| Versionierung | Dateipfad und **SHA-256 des Eingabe-GeoJSON** werden im Kennzahlenbericht erfasst; spätere Masken können verglichen werden |

**Derzeitige Maske:** `data/processed/street_space/fmzk_strassenraum.geojson`. Sie enthält noch FMZK-Originalobjekte und viele Attribute; **die nachfolgenden Module dürfen diese nicht benötigen**.

Ein späteres Verfahren – zum Beispiel eine verbesserte Kataster-Methode oder eine ganz andere Straßenraum-Erkennung – darf dieselbe Schnittstelle liefern. Dann müssen wir beim Kennzahlenmodul nur den Dateipfad ändern:

```bash
.venv/bin/python -m scripts.measure_ground_greening \
	--street-geojson data/processed/alternative/strassenraum.geojson
```

Wichtig: Eine solche neue Maske muss auch räumlich zum zugrunde liegenden FMZK-Testgebiet passen. Inkompatible Ausschnitte werden nicht heimlich verarbeitet.

## 3. Bodenbegrünungsanteil – jetzt implementiert

**Eigenständiges Kennzahlenmodul:** `scripts/measure_ground_greening.py`.

**Input 1:** ausschließlich **Straßenraum-Polygon-GeoJSON** laut Vertrag v1. Dabei werden Quellattribute absichtlich ignoriert.

**Input 2:** der **FMZK-Testausschnitt** via dem gemeinsamen `fmzk_source`-Adapter. Die bodengebundenen Grünflächen werden derzeit über `F_KLASSE IN (58,69)` identifiziert. `59` und andere Klassen werden nicht automatisch als Grün gezählt.

**Definition:**

```text
Nutzfläche Bodenbegrünung [m²] =
  Fläche( Vereinigen(FMZK-Grünpolygone 58/69) ∩ Straßenraumgeometrie )

Straßenraumfläche [m²] =
  Fläche( Vereinigen(alle Straßenraum-Polygone) )

Bodenbegrünungsanteil [%] =
  100 × Nutzfläche Bodenbegrünung / Straßenraumfläche
```

Alle Flächenberechnungen erfolgen **metrisch in EPSG:31256**. Dies verhindert das Doppeltzählen sich überdeckender FMZK-Geometrien und erlaubt neue Straßenraumquellen. Der Grün-Numerator wird **an der Straßenraumgrenze geschnitten**, unabhängig davon, ob Modul 2 ganze FMZK-Polygone ausgibt.

**Kennzahl ist bodengebunden:** Baumkronen über Asphalt oder Gehsteigen sind **keine** Bodenbegrünung, Gründächer sind nicht automatisch bodengebundene Straßenraumbegrünung. Außerdem ist diese Kennzahl nur so vollständig wie die FMZK-Grünklassifizierung und die vorläufige Straßenraumgrenze.

**Ausführung:**

```bash
.venv/bin/python -m scripts.measure_ground_greening
```

**Outputs (lokal; `data/processed/bodenbegruenung/`):**

- `bodenbegruenung_bericht.json`: Straßenraum-Gesamtfläche, vereinigte Boden-Grünfläche, Prozentanteil, Fläche nach Klasse 58/69, gegenseitige Überlagerungen, Zahl betroffener FMZK-Objekte, fehlende FMZK-Abdeckung, Eingabe-SHA-256 und Methodenhinweise.
- `bodenbegruenung_flaechen.geojson`: Zur Sichtprüfung nach Straßenraummaske **beschnittene Grün-Teilflächen** mit FMZK-FID und Klasse; die statistische Gesamtfläche wird **aus einer Vereinigungsgeometrie**, nicht aus der bloßen Addition dieser Features, berechnet.

**Kein Automatikschritt** zur Übernahme noch ungeklärter Grünflächen außerhalb der Straßenmaske. Sie bleiben für Qualitätskontrolle und spätere Verfeinerung erhalten. Die Gesamtrate bezieht sich ausschließlich auf die aktuelle vorläufige Maske.

### Erster lokaler Referenzlauf – Bodenbegrünung (13.10.2026)

Das Modul wurde nach der Implementierung mit den **tatsächlichen lokalen Daten des FMZK-Testausschnitts** ausgeführt. Die hier dokumentierten Werte stammen aus `data/processed/bodenbegruenung/bodenbegruenung_bericht.json` (Schema-Version **1**, Messzeitpunkt **2026-10-13 20:49:26 UTC**). **Der Ergebnisbericht und die GeoJSON-Daten werden nicht in Git eingecheckt**; folgende Angaben dokumentieren ihren Stand reproduzierbar.

| Ergebnis | Wert |
| --- | ---: |
| Straßenraumfläche, vereinigt (Nenner) | **46.630,56 m²** |
| Bodenbegrünte Straßenraumfläche, vereinigt (Zähler) | **889,18 m²** |
| **Bodenbegrünungsanteil** | **1,9069 %** (gerundet **1,91 %**) |
| FMZK-Klasse 58 innerhalb der Straßenmaske | 0,001653 m² |
| FMZK-Klasse 69 innerhalb der Straßenmaske | 889,182788 m² |
| FMZK-Objekte insgesamt | 2.401 |
| FMZK-Grünobjekte (Klassen 58/69) insgesamt | 276 |
| Grünobjekte mit positiver Überschneidung zur Straßenmaske | 107 |
| Objekte in der Straßenraum-Eingabemaske | 487 |
| Überlagerung zwischen Grünklassen 58 und 69 | 0,00 m² |
| Straßenraum ohne FMZK-Flächendeckung | 0,038146 m² |
| Anzahl reparierter Geometrien der Straßenmaske | 0 |
| Summe außerhalb der Testausschnittsgrenze, vor dem Schnitt | 0,177884 m² |

**Eingaben dieses Referenzlaufs:**

- **Straßenraum-Maske:** `data/processed/street_space/fmzk_strassenraum.geojson`; SHA-256 **`dc53cd78d0bcd5cb242529e126a969f1be6ca5d27487ff1e85ee684654d7fc11`**. Der Hash gilt **für die konkreten Datei-Bytes**, nicht für das abstrakte Verfahren oder die Straßenraumgeometrie unabhängig von der Kodierung.
- **FMZK-Ausschnitt:** `data/processed/fmzk_test.gpkg`, Layer `fmzk`, EPSG:31256.
- **Test-BBOX:** `16.361012,48.221226,16.366948,48.224902` (EPSG:4326).
- **Berechnung:** FMZK-`F_KLASSE` 58/69, mit der vereinigten Straßenraumgeometrie geschnitten; Nenner ist die vereinigte Straßenraumfläche. Diese Prozentzahl ist **nur für die aktuelle Straßenraum-Version und diesen Ausschnitt** gültig.

**Einordnung / Qualität:** Der Benutzer hat die Darstellung bzw. das erste Ergebnis qualitativ mit **„Das schaut sehr gut aus!“** bewertet. Das ist eine positive Sichtkontrolle, **keine quantitativ belegte Klassifikationsgenauigkeit**. Mit lediglich rund **0,002 m²** aus FMZK-Klasse 58 stammt die hier gezählte Bodenbegrünung faktisch vollständig aus Klasse 69. **Warum** Klasse 58 so wenig beiträgt, ist noch nicht verifiziert: Das kann mit den konkreten Grünflächen, der vorläufigen Straßenraumzuordnung oder Grenzüberschneidungen zusammenhängen. Die Zahl darf nicht als Beleg dafür interpretiert werden, dass Klasse 58 grundsätzlich nicht im Straßenraum vorkommt.

Der Bericht meldet praktisch vollständige FMZK-Flächendeckung (nur **0,038 m²** ohne Quellüberdeckung). Die rund **0,178 m²** Eingabegeometrie außerhalb des Testausschnitts wurden bei der Ermittlung der Maske zugeschnitten; dieser kleine Wert ist als **numerischer/geometrischer Prüfhinweis**, nicht als Beleg fehlerfreier Koordinaten, zu lesen. Änderungen am Straßenraum-Modul, an FMZK-Daten oder Grünklassendefinitionen führen zu **einem neuen Messstand**; den heutigen Bericht und seinen Masken-Hash als Vergleich erhalten.

**Festlegung:** Modul 3 bleibt in dieser Fassung als eigenständig arbeitendes, getestetes Modul bestehen. Erst konkrete Gegenbeispiele oder eine neue fachliche Anforderung sind Anlass, die Flächenklassen bzw. Straßenraum-Maske anzupassen. Nächster eigenständiger Schritt ist die **Datenquelle und Methodik für Modul 4 – Kronenüberschirmung** festzulegen; Bodenbegrünung wird dadurch nicht rückwirkend ersetzt oder mit der Kronenfläche addiert.

## 4. Kronenüberschirmung – erste Vergleichsmodule implementiert

Für Modul 4 ist eine **zweite austauschbare Schnittstelle** definiert: **Baumkronen-GeoJSON-FeatureCollection mit Polygon/MultiPolygon in EPSG:4326**, unabhängig davon, ob die Kronen als Kreise aus Baumstandorten oder aus Raster-/Bilddaten entstanden sind. Modul 4 enthält:

- **Datenadapter:** `scripts/fetch_vienna_trees.py` für kleinen WFS-Ausschnitt des Wiener Baumkatasters (`ogdwien:BAUMKATOGD`).
- **Kronen-Provider A:** `scripts/build_canopy_circles.py` ausschließlich für den Wiener WFS-Baumkataster, mit dessen geprüften Klassenmittelwerten. **OSM ist in A ausdrücklich nicht mehr zulässig.**
- **Kronen-Provider B:** `scripts/build_canopy_combined.py` für den Wiener Baumkataster plus OSM-Einzelbäume und approximierte Baumreihen; Quelladapter `scripts/fetch_osm_trees.py`, übernommene Dubletten-/Samplinglogik in `scripts/canopy_osm_merge.py`. Beide teilen nur die reinen Kronen-Geometriehelfer in `scripts/canopy_tree_common.py`; Schätzungen unbekannter OSM-Kronen sind als solche ausgewiesen.
- **Berechnung:** `scripts/measure_canopy_cover.py` (Kronen-Union ∩ Straßenraum-Union, geteilt durch Straßenraum-Union), völlig unabhängig vom konkreten Kronen-Provider.
- **Methodenvergleich:** `scripts/compare_canopy_methods.py` zum Vergleich mehrerer Kronenmasken einschließlich Überlagerung und nur einseitig ausgewiesener Flächen.

Für das **Grünraummonitoring 2023 Wien** (50 cm Quellraster, **Baumschicht als Klasse 3**) wurde ein separater Diagnose- und Kronenprovider ergänzt: `scripts/probe_grm2023_wms.py` und `scripts/build_canopy_grm2023.py`. Der tatsächliche WMS-Ausschnitt (923×858 px) wurde anhand der neun deckenden Klassenfarben und seiner Legende überprüft: **#38A800 = Baumschicht** (71.892 Pixel). Der Kronenprovider wandelt diese Pixel in ein EPSG:4326-Polygon-GeoJSON um, das **ohne Änderungen am Messmodul** verarbeitet wird. Die WMS-Daten sind ein Renderergebnis, kein garantiert originalgetreues 50-cm-Rohdatenraster. Eine eigene BEV-Infrarot-Bildklassifikation bleibt eine spätere Option. **Erster vollständiger Vergleich für denselben Straßenraum: A (Baumkataster-Kronenkreise) 3.647,05 m² / 7,82 %, C (GRM2023-Baumschicht) 4.358,69 m² / 9,35 %, räumliche IoU 58,02 %.** Der GRM2023-Rasterexport wurde gesondert geprüft: 71.892 Baum-Pixel auf 7.578 horizontale Zellenläufe und 1.298 Polygonbestandteile verteilt; die aus Pixelzahl berechnete und die polygonisierte Gesamtfläche stimmen überein (17.958,20 m² im WMS-Bildausschnitt). Der Unterschied zum Straßenraumwert ergibt sich aus dem **Schnitt mit der vorläufigen Straßenraummaske**. Fachliche Genauigkeitsprüfung anhand von Orthofotos/Referenzflächen bleibt ausständig. [Messdetails und Vergleichs-Prüfsummen](Modul-4-Baumkronen-Vergleich.md#erster-vollständiger-lokaler-referenzvergleich-ac-1314102026).

**A/B-Trennung (14.10.2026):** Die Quellenkombination der Kartensammlung liegt ursprünglich in [`kartensammlung-overlay-builds/baumkataster/build.mjs`](https://github.com/peter-alexander/kartensammlung-overlay-builds/blob/main/baumkataster/build.mjs), nicht im Karten-Frontend. Methode B übernimmt dessen Vorrang Wien → OSM-Einzelbaum → Baumreihen, 4-m-/0,75-m-/3-m-Dublettenprüfungen und Standard-Baumreihenabstand 8 m. Fehlende OSM-Kronenmaße werden in B nach der bisherigen Solar-3D-Logik ausdrücklich geschätzt und protokolliert, alternativ ist ein strenger Durchlauf ohne solche Schätzungen möglich. Die Wiener Einzelkronen von A bleiben geometrisch unverändert. **Der erste reale Overpass-Lauf für B ist abgeschlossen:** 140 OSM-Einzelbäume, 128 durch Wiener Standortnähe ausgeschlossen, zwölf OSM-Standorte ergänzt, aber nur vier zusätzliche Kronen mit Kontakt zum Testgebiet; keine OSM-Baumreihen. B ergibt **3.678,65 m² / 7,89 %** (gegenüber A **3.647,05 m² / 7,82 %** und C **4.358,69 m² / 9,35 %**). Das ist gegenüber A nur **+31,60 m²**; alle A-Kronenflächen sind in B enthalten (IoU **99,14 %**). Die fehlenden OSM-Kronendurchmesser und mögliche private, nicht kartierte Bäume bleiben Unsicherheiten; alle drei Referenzstände sind separat dokumentiert.

**BEV-WMS-Referenzergebnis (13./14.10.2026):** Der erste reale Lauf lieferte fünf gültige PNGs à **943 × 878 Pixel**. RGB und IR sind durch RGIR/RIRB und die weiteren Replikate **in neun von elf Kanalvergleichen exakt pixelgleich** bestätigt; nur `IRGB` weicht in den dort dargestellten Rot- und Grünkanälen ab. Die Methode D prüft nun ausdrücklich zwei getrennte Kennzahlen: **Kernkanalkonsistenz (RGB/IR plus unabhängige Replikate)** und **Gesamtkonsistenz aller WMS-Darstellungen**. Die bekannte IRGB-Anomalie wird weiterhin offengelegt und darf nicht als radiometrische Kalibrierung interpretiert werden. A/B/C bleiben unverändert.

**Methode D3 – zweistufige Vegetationsobjekte und Kronenkandidaten (14.10.2026):** `scripts/segment_bev_vegetation.py` liest unveränderte, lokal validierte BEV-WMS-RGB-/IR-Raster, verwendet **0,10** als ursprüngliche Vegetationsmaske und **0,20** als starken Signal-Kern. Eine 8fach-zusammenhängende Hysterese und die Messung von Objektgeometrie und RGB-Binnenkontrast erzeugen **explorative Kategorien**, keine amtlichen Baumkronen. Der neue Ordner `data/processed/baumkronen/bev_segmentierung/` enthält vier georeferenzierte Prüfraster sowie Objekt-/Provenienzberichte. Die texturellen Schwellwerte und Formmerkmale werden erst anhand unabhängiger visueller Referenzflächen beurteilt. Kein Export von Kronen-GeoJSON, kein neuer Überschirmungsgrad und **keine Änderung** von A/B/C, D1 oder D2.

**Methode D2 – Vegetationsindikator ohne Höhenmodell (14.10.2026):** `scripts/analyze_bev_vegetation.py` arbeitet **rein lokal** auf bereits validierten BEV-WMS-`RGB`- und `IR`-PNGs. Es prüft Quell-SHA-256, Pixelgeometrie, EPSG:3857 und anhand des alten oder neuen Diagnoseberichts die belegten Kernkanalreplikate. Die Bildwerte werden ausschließlich als **unkalibrierter WMS-Index** `(NIR−R)/(NIR+R)` verarbeitet. Kontinuierliches Index-Raster, vier separat georeferenzierte Schwellenmasken sowie Vergleichsbild/Prüfbericht entstehen im eigenen Ordner `data/processed/baumkronen/bev_vegetation/`. **Keine Baumkronengeometrie, keine Straßenraumfläche, kein Überschirmungswert**; D2 wird erst anhand echter Bildbeispiele fachlich beurteilt. Der ursprüngliche WMS-Diagnoseadapter und die Methoden A/B/C bleiben unverändert.

**Methode D – primärer WMS-Quelladapter:** `scripts/probe_bev_wms.py` prüft ab 14.10.2026 die fünf bereits in `Kartensammlung/src/app/basemaps/providers/imagery.js` verwendeten BEV-Darstellungen `bev:RGB`, `bev:IRGB`, `bev:RGIR`, `bev:RIRB` und `bev:IR`. Das Modul ruft für die unveränderte FMZK-Testregion ein identisches EPSG:3857-Pixelgitter ab und prüft deckungsgleich gespeicherte PNG-/PGW-/PRJ-Bilder auf interne Kanalübereinstimmung. Die WMS-Rot-/NIR-Werte sind **keine nachgewiesenen radiometrischen Rohwerte**, auch bei identischem Rendering. Deshalb erzeugt der Adapter weder NDVI noch Kronenpolygone. Die optionale lokale Original-RGBI-/NIR-Diagnose bleibt als **eigener Fallback** erhalten; A/B/C und die gemeinsame Überschirmungsberechnung ändern sich nicht. [D-WMS-Diagnose](Modul-4-Baumkronen-Vergleich.md#vorrangiger-erster-versuch-bev-wms-aus-der-kartensammlung-d0-implementiert).

**Methode D (BEV RGBI) – optionale Originaldatei-Vorstufe D1:** `scripts/probe_bev_rgbir.py` ist als separater Rasteradapter implementiert. Es akzeptiert wahlweise ein RGBI-TIFF mit vier Bändern oder ein RGB-/NIR-Dateipaar mit drei und einem Band. GDAL prüft Projektion, Footprint, Bänder und optional identisch georeferenzierte Zuschnitte des FMZK-Testausschnitts. Eine spektrale Baumklassifikation und neue Kronenpolygone sind bewusst **noch nicht implementiert**, weil Datenjahr, tatsächliche Rot-/NIR-Bandzuordnung und Baum-/Rasen-Unterscheidung noch fachlich geprüft werden müssen. Der Providervertrag von Modul 4 und die Methoden A/B/C werden dadurch nicht verändert. [BEV-Quellenprüfung D1](Modul-4-Baumkronen-Vergleich.md#variante-d-bev-orthofoto-rgbi--quellenprüfung-d1-14102026).

Der Überschirmungsgrad bleibt **unabhängig von der Bodenbegrünung** und darf nicht zur Begrünungsquote addiert werden. Eine Kronenquelle von außerhalb des Straßenraums ist relevant, sobald deren Kronenpolygon über den Straßenraum reicht. Die **WFS-Abfrage mit 252 Baumstandorten**, WMS-Diagnose und beide lokalen Kronen-Vergleichsläufe wurden bereits durchgeführt; ein räumlicher Differenzvergleich über Orthofoto ist der nächste fachliche Schritt.

**[Modul-4-Methodik, Vergleichsvarianten und Prüfschritte](Modul-4-Baumkronen-Vergleich.md).**

## 5. Weitere Kriterien – offen

Weitere getrennte Module können unter anderem zusätzliche räumliche und nutzungsbezogene Merkmale auswerten. Details und Datenquellen werden erst festgelegt, wenn sie benötigt werden. Auch die spätere Segmentierung, Aggregation und eine Gartenstraßen-Bewertung sind eigene Schritte, **nicht** Teil des jetzigen Bodenbegrünungsmoduls.

## Test-, Änderungs- und Vergleichsprinzipien

- **Modul 2 darf ausgetauscht werden**, ohne Modul 3 umzuschreiben: Der Test mit einem **attributfreien Polygon-GeoJSON** sichert das.
- Gleiche Eingabemaske + gleiche FMZK-Extraktion ergeben die gleichen geometrischen Kennzahlen; nur Zeitstempel unterscheiden sich.
- Flächen dürfen weder im Nenner (mehrere Straßenraumobjekte) noch im Zähler (überlappende Grünpolygone) mehrfach gezählt werden.
- Wenn die Straßenmaske Teile enthält, die durch **keine FMZK-Fläche** abgedeckt sind, wird dies ausgewiesen, nicht stillschweigend als vollständige Kartierung dargestellt.
- Ergebnisse sind **für den Testausschnitt**, nicht gleichzusetzen mit einer geprüften Genauigkeit für ganz Wien.
- Vor einem neuen oder revidierten Modul Datenvertrag, eindeutige Einheiten, Testfälle und eine neue fachliche Prüfung dokumentieren; nicht mehrere Schwellen gleichzeitig ohne Vergleichslauf ändern.

Die Daten und berechneten GeoJSONs bleiben lokal unter `data/`, nur Skripte, Tests und Dokumentation liegen auf GitHub.
