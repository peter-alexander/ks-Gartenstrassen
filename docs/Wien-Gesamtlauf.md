# Wienweiter Gartenstraßenlauf – ausführbarer Ablauf

**Neue Regelversion (15.10.2026):** FMZK-Klasse **25** mit `F_KLASSE_TEXT = "Gehweg, Radweg"` wird fest zum Straßenraumkern **21/23/24/25/33/39** gerechnet. Das vergrößert möglicherweise den Straßenraum-Nenner und erfordert eine neue Kataster-Grundstücksauswahl sowie Neuaufteilung und Neuberechnung der Kennzahlen. Bisherige Alsergrund-Zahlen wurden vor dieser Änderung gemessen und gelten als historischer Pilot der alten Methode. Alte Kataster-/Straßenraumkacheln werden wegen fehlender oder abweichender Regelversion abgewiesen. Unveränderte FMZK-Originaldaten und BEV-Rohkacheln bleiben wiederverwendbar.

**Stand 15.10.2026:** Der Alsergrund-Pilot mit 586 eindeutigen FOW=3-GIP-Abschnitten und Boden-/GRM2023-Messung wurde lokal erfolgreich ausgeführt. **Ein vollständiger Wien-Lauf wurde noch nicht ausgeführt**; Zeitbedarf, Datenvolumen und technische Vollständigkeit sind daher nicht behauptbar.

Die Berechnung verwendet weiterhin die vorhandenen Module. Neu sind der phasenweise Treiber **scripts/run-wien-gartenstrassen.sh** und der reine Ergebnisexport **scripts/wienwide_result_export.py**. Die vereinbarten **100 m²** gelten ausschließlich für den regulären Export, nicht für die Quellverarbeitung, die Voronoi-Aufteilung oder die QA-Bilanz.

## Voraussetzungen

- Das vollständige lokale Original **FMZK_WIEN_GP.gpkg** in EPSG:31256.
- Für die neue Klassifikationsregel **frische Eingabe- und Ergebnisverzeichnisse** verwenden (Vorgabe `data/processed/wienweit/wien/`). Veraltete BEV-Katasterberichte aus vorigen Läufen nicht als unveränderte Quelle übernehmen.
- Die Python-Venv mit **requirements-analysis.txt** und GDAL-CLI (ogr2ogr).
- Abrufbarkeit der MA41-AOI, GIP-WFS-, BEV-Kataster- und GRM2023-WMS-Quellen. Bestehende geprüfte Kachel-Caches bleiben erhalten.
- Genügend lokaler Speicher für Eingangs-, Zwischen- und vollständige QA-Ergebnisdateien. Es gibt noch keinen real gemessenen Wien-Benchmark.

## Start

~~~bash
git pull --ff-only

# Komplett, mit Fehlerstopps und wiederverwendbaren Caches:
bash scripts/run-wien-gartenstrassen.sh

# FMZK liegt außerhalb des vorgeschlagenen data/raw/-Pfades:
bash scripts/run-wien-gartenstrassen.sh \
	--fmzk /absoluter/pfad/FMZK_WIEN_GP.gpkg
~~~

Für den **ersten Wien-Lauf** empfehlen sich kontrollierte Etappen:

~~~bash
# Amtliche Wien-AOI (alle 23 Bezirke) und festes 1-km-Raster.
bash scripts/run-wien-gartenstrassen.sh --until grid

# GIP-WFS-Caches vollständig aufbauen, dann globalen Index.
bash scripts/run-wien-gartenstrassen.sh --from gip-fetch --until gip-index

# FMZK-/Kataster-Eingaben und metrische Straßenraumkacheln.
bash scripts/run-wien-gartenstrassen.sh --from inputs --until street

# GIP-V0 und vierlagiges QA-GeoPackage.
bash scripts/run-wien-gartenstrassen.sh --from partition --until qa

# Gerenderte GRM2023-Baumschicht vollständig laden und prüfen.
bash scripts/run-wien-gartenstrassen.sh --from grm-fetch --until grm-build

# Boden-/Kronenmessung, reguläre Ausgabe und Benchmark.
bash scripts/run-wien-gartenstrassen.sh --from measure --until benchmark
~~~

**--from** und **--until** begrenzen die **ausgeführten Schritte**, nicht den geografischen Untersuchungsraum. Nach einem Abbruch kann die betroffene Phase wiederholt werden; bestehende vollständige Gesamtdateien werden nicht überschrieben. Geänderte Quellhashes, unvollständige Caches oder unzulässige Geometrien sind zu prüfen, nicht stillschweigend zu ignorieren.

## GIP-WFS-Duplikate beim Wien-Lauf (15.10.2026)

Der erste reale Wien-Lauf erzeugte die AOI **414,87 km² / 489 Kacheln**
und lud alle **489/489** GIP-Kacheln in **8 min 21 s inklusive
anschließendem fehlgeschlagenen Indexversuch**. Bei der ersten
Indexierung wurde die mehrfach vorhandene Achsen-ID **10026184**
innerhalb einer Kachel festgestellt. Das ist ein **Indexkonflikt,
kein unvollständiger WFS-Download**.

Die wienweite Indexierung behandelt innerhalb einer Kachel
wiederholte GIP_OBJECTIDs so:

- **Exakt gleiche Geometrie und dieselben graphrelevanten Attribute:**
  Eine physische GIP-Achse wird genau einmal übernommen. Bei Achsen
  darf ausdrücklich nur REG_STRNAME variieren, weil dasselbe Straßenstück
  mehrere amtliche Routenbezeichnungen haben kann. Die ursprünglichen
  WFS-IDs und REG_STRNAME-Werte bleiben mitsamt Zahl ihrer
  Kachelvorkommen in der Index-Tabelle axis_source_variants erhalten.
  Die Summen stehen in den Metadaten des GIP-Indexes.
- **Abweichende Geometrie oder andere fachliche Attribute:** Abbruch
  mit Kachel-ID, GIP-ID, beiden Feature-Indizes, WFS-IDs und Hinweis
  auf den Unterschied. **Keine automatische Auflösung**.
- Dieselbe Ausnahme für REG_STRNAME gilt kachelübergreifend; alle
  übrigen graphrelevanten Attribute werden nun auch kachelübergreifend
  mit der ersten Quelle verglichen. GIP-Graph und Voronoi verwenden
  nach wie vor genau eine Achse pro gültiger GIP-ID.

**Diagnose für GIP 10026184 (Brunner Straße):** Die Fundstellen aus
den echten Wien-Caches zeigen zwei deckungsgleiche WFS-Achsen mit
GIP_OBJECTID 10026184 und identischen Endknoten 10355942/10355873.
Die einzigen Unterschiede sind WFS-Feature-ID
STRASSENGRAPHOGD.61196089 / STRASSENGRAPHOGD.61196034 und die
Routenbezeichnungen B12 / B13a. Jede Variante taucht in zwei
benachbarten Kacheln auf. Damit liegt genau der erlaubte
Routenbezeichnungsfall vor; kein geometrischer Konflikt.

Die gesamte Wien-Indexierung wurde nach dieser Änderung noch nicht
auf den lokalen 489 Kacheln ausgeführt.

Nach git pull --ff-only wird der lokal vollständige Cache direkt
weiterverwendet:

~~~bash
bash scripts/run-wien-gartenstrassen.sh --from gip-index --until gip-index
~~~

Tritt bei GIP-ID 10026184 weiterhin ein Konflikt auf, lassen sich
sämtliche Vorkommen **ohne neue WFS-Anfragen** mit den gecachten
Originalgeometrien und Attributen anzeigen:

~~~bash
.venv/bin/python -m scripts.wienwide_gip diagnose \
	--manifest data/processed/wienweit/wien/raster.json \
	--fragments data/processed/wienweit/wien/gip_fragmente \
	--gip-id 10026184
~~~

Für die Diagnose-ID 10026184 ist dieser Vergleich bereits erfolgt und
hat die oben beschriebene reine REG_STRNAME-Variante gezeigt. Bei einem
**weiteren** Konflikt erlaubt derselbe Diagnosebefehl die gezielte
Untersuchung; Geometrieabweichungen bleiben weiterhin ein Abbruchgrund.

## FMZK-Zuschnitt mit flächenlosen Quell-Features (15.10.2026)

Der erste vollständige Wien-Eingabelauf erreichte nach der erfolgreich
fertiggestellten Kachel x-000007_y+000332 die folgende Kachel
x-000006_y+000332. Deren FMZK-Zuschnitt enthielt 5784 Features.
Der nachfolgende Katasterlauf meldete bei FID **163939** eine
"flächenlose oder nicht-polygonale Geometrie". Aus dem Fehler allein
ist **nicht belegbar**, ob die betroffene Geometrie bereits im Original
flächenlos war oder erst beim BBOX-Zuschnitt so wurde.

Der gemeinsame **fmzk_source.load_polygons**-Reader behandelt deshalb
streng nach dem tatsächlich verbleibenden Areal:

- Polygonale gültige Geometrie mit positiver Fläche wird verarbeitet,
  **auch wenn die Fläche extrem klein ist** (kein 100-m²-Filter hier).
- Ungültige Geometrie wird wie bisher mit shapely.make_valid geprüft;
  eine positiv-flächige reparierte Polygongeometrie wird erhalten.
- Geometrien, die auch nach etwaiger Reparatur **keine positive
  Polygonfläche** haben, werden nur von der Berechnung ausgenommen.
  FID, Klasse, Geometrietyp und Grund erscheinen in der Konsole sowie
  in den Kataster- und Straßenraum-Berichten unter
  fmzk_geometrieereignisse. Das FMZK-GeoPackage bleibt unverändert.
- Positiv-flächige Geometrien mit ungeeigneter Geometriestruktur,
  verlorene Features gegenüber dem Extraktionsmanifest oder fehlende
  Klassenattribute führen **weiterhin zum Abbruch**.
- Die Anzahl der tatsächlich gelesenen **GPKG-Rohfeatures** muss exakt
  zur ursprünglichen feature_count des Extraktionsmanifests passen.
  Ohne Flächenbeitrag ausgeschlossene FIDs bleiben einzeln in der
  Bilanz aufgeführt.

Der erfolgreiche Katasterbericht vor dem Abbruch zeigt **111 x D**.
Das bedeutet nur, dass keine optionalen vollständigen
Grundstücks-API-Details abgefragt wurden; die Vektorkacheln mit
Nutzungsflächen sind trotzdem verfügbar. D ist hier kein Hindernis
für die Straßenraumvorstufe.

Der unterbrochene Lauf kann mit vorhandenem FMZK-Zuschnitt und
geprüftem BEV-Cache direkt wiederaufgenommen werden:

~~~bash
git pull --ff-only
bash scripts/run-wien-gartenstrassen.sh --from inputs --until inputs
~~~

Vorherige Ausgaben müssen **nicht gelöscht** werden. Ein vollständiger
neuer Wien-Eingabelauf wurde nach der Anpassung **noch nicht
verifiziert**.

## Pfade und Parameter

| Element | Standard |
| --- | --- |
| AOI | data/raw/bezirke-wien/wien.geojson |
| FMZK | data/raw/FMZK_WIEN_GP.gpkg |
| Analyse | data/processed/wienweit/wien/ |
| Raster | 1000 m, Halo 75 m |
| GIP-V0 | Stützpunkte 5 m, Knotenradius 7 m, maximaler Achsabstand 25 m, regulär FOW=3 |
| Kataster | 1500 Grundstücke je Analyse-Kachel als technisches Schutzlimit |
| GRM-GetMap | 0,5 s Pause zwischen neuen Abrufen |
| Ergebnisfilter | Globale GIP-Abschnittsfläche ab 100 m² |

**Vollständige Auswertung, unverändert und ohne Mindestflächenfilter:**

data/processed/wienweit/wien/begruenung_grm/

- **gip_abschnitte_begruenung.csv:** vollständige Kennzahlen aller GIP-IDs.
- **gip_abschnitte_begruenung.gpkg:** vollständiges QA-GeoPackage mit allen Teilflächen, Knotenbereichen, Sonderachsen und Restflächen.
- **begruenung_bericht.json:** Messbilanz und Provenienz.

**Reguläre Veröffentlichung, Mindestfläche 100 m²:**

data/processed/wienweit/wien/veroeffentlichung_100m2/

- **gip_abschnitte.csv:** gefilterte globale Abschnittszeilen.
- **gip_abschnitte.geojson:** genau ein in EPSG:31256 vereinigtes und anschließend nach EPSG:4326 transformiertes Feature pro ausgewählter GIP-ID. Attribute einschließlich **boden_pct** und **grm_kronen_pct** entsprechen den vollständigen Messungen.
- **export_bericht.json:** Quell-SHAs, vollständige/ausgegebene/ausgelassene GIP-IDs und Flächensummen.

Ein Abschnitt aus zwei Kachelfragmenten zu je 60 m² wird insgesamt als 120 m² berücksichtigt und **nicht** aussortiert. Eine eigenständige GIP-ID unter 100 m² erscheint dagegen nicht im regulären Ergebnis; ihre Geometrie und ihre Kennzahlen bleiben in den vollständigen QA-Daten erhalten. Der Export führt **keine Mittelung der Prozentwerte** durch.

Die **gip_abschnitte.geojson** kann nach erfolgreicher Sichtkontrolle in die Kartensammlung als **/Maps/gip_abschnitte.geojson** übernommen werden. Vorher Größe und Ladezeit testen; eine große ungekachelte GeoJSON ist nicht notwendigerweise das endgültige Auslieferungsformat.

## QA und fachliche Grenzen

1. Vollständige Kachelanzahl, geometrietopologische Straßenraumbilanz und Quell-SHAs müssen geprüft sein.
2. Sonderachsen mit FOW ungleich 3, Kreuzungsbereiche und Restflächen bleiben außerhalb der derzeitigen **regulären** GIP-Abschnittsquote, jedoch in der Gesamtbilanz.
3. Bodenbegrünung beruht auf der geometrisch vereinigten FMZK 58/69; GRM2023 ist eine **gerenderte WMS-Baumschicht**. Die beiden Anteile dürfen nicht addiert werden.
4. Der Kachel-Cache bietet technische Prüfsummen, aber bei langem GIP-WFS-Abruf **keine Garantie eines zeitlich konsistenten amtlichen Snapshots**.
5. Ein erfolgreicher Wien-Lauf ersetzt keine Ortsprüfung in QGIS/Kartensammlung, vor allem an großen Kreuzungen, Sonderachsen, Kachelgrenzen und Abschnitten mit extremen Prozentwerten.
6. Keine automatische Klassifikation als Gartenstraße und keine MBTiles-Ausgabe in dieser Phase.

## Regressionstests

~~~bash
.venv/bin/python -m unittest discover \
	-s tests -p 'test_wienwide_result_export.py' -v
~~~

Die Tests prüfen den Filter auf vollständige GIP-IDs statt auf Kachelfragmente, NULL-Kronenwerte sowie Abbruch bei widersprüchlichen Flächen.
