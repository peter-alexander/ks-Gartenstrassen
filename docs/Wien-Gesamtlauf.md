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

## Kernfreie FMZK-Kacheln am Wiener Stadtrand (16.10.2026)

Nach erfolgreicher Bearbeitung der Kachel x+000009_y+000333
(1455 FMZK-Features, 34 Kataster-Treffer) trat beim vorbereiteten
FMZK-Zuschnitt x+000015_y+000333 (20 Features) der Fehler
"Keine FMZK-Kernflächen vorhanden" auf.

Das bedeutet **nicht**, dass der FMZK-Download leer oder defekt
ist: Die Extraktion hat 20 gültige Features geliefert, aber nach
der aktuellen V0-Straßenraumregel muss ein Grundstück zunächst
eine FMZK-Kernfläche aus 21/23/24/25/33/39 schneiden, bevor seine
BEV-nfl-Flächen für andere FMZK-Klassen herangezogen werden.

Neue Behandlung von kachelgroßen Rand-/Halo-Ausschnitten:

- Die gesamte lokale FMZK-Extraktion wird wie zuvor anhand ihres
  Manifests eingelesen und auf gültige Polygonflächen geprüft.
- Enthält **der gesamte Ausschnitt inklusive Halo** keine einzige
  Straßenkernklasse, werden **keine BEV-Kacheln geladen**. Stattdessen
  wird ein nachvollziehbarer Kataster-Nullbericht mit dem Kennzeichen
  kein_fmzk_kern_im_ausschnitt und dem Hash der tatsächlich
  eingelesenen FMZK-Datei geschrieben. Grundstücke = 0, BEV-Tiles = 0.
- Nur bei einem passend geprüften Kataster-Nullbericht wird die
  Straßenraumkachel explizit mit 0 m² erzeugt. Die
  Methoden-/FMZK-/Berichts-Prüfsummen bleiben beim Wiederaufnehmen
  verbindlich; ein echter Kern, insbesondere Klasse 25, darf
  **nicht** durch den Nullfall übersprungen werden.
- Die Nullfläche bedeutet **keine positive Straßenraumzuordnung nach
  unserer V0-Regel**, nicht den amtlichen Nachweis, dass überhaupt
  keine Verkehrsfläche im Gebiet existiert. Bestehende Nicht-Kern-
  FMZK-Flächen werden nicht als positiv klassifiziert.
- Die globale GIP-Indexierung und die bisher erfolgreichen
  FMZK-/Katasterkacheln bleiben vollständig erhalten. Die
  V0-Flächenbilanz zählt auch Nullkacheln als erfolgreich
  bearbeitete AOI-Kacheln.

Nächster Fortsetzungsschritt:

~~~bash
git pull --ff-only
.venv/bin/python -m unittest discover -s tests \
	-p 'test_analyze_kataster.py' -v
.venv/bin/python -m unittest discover -s tests \
	-p 'test_wienwide_kataster.py' -v
bash scripts/run-wien-gartenstrassen.sh --from inputs --until inputs
~~~

Ein vollständiger realer Wien-Eingabelauf unter der neuen
Nullkern-Regel ist noch nicht verifiziert.

## FMZK-GeometryCollection mit Polygonfläche (16.10.2026)

Nach der erfolgreichen Verarbeitung von x+000018_y+000333 und einer
kernfreien Kachel x-000010_y+000334 (15 FMZK-Features) stoppte die
FMZK-Vorstufe bei x-000009_y+000334 (161 Features) an
**FID 782170**, weil der GPKG-Reader eine
**GeometryCollection mit positiver Fläche** erhielt. Die Ursache
in der Originalquelle oder beim BBOX-Zuschnitt ist aus dem Log allein
nicht zu entscheiden.

Die bisherige strenge Blockade wurde auf eine
flächenkonservierende Normalisierung eingegrenzt:

- Alle Polygon- und MultiPolygon-Bestandteile einer GeometryCollection
  werden rekursiv erhalten und zu einer Polygongeometrie vereinigt.
  Linien und Punkte können keinen Flächenbeitrag leisten.
- **Die ursprüngliche Flächensumme der GeometryCollection und
  die vereinigte Polygonfläche müssen bis auf rein numerische
  Toleranz übereinstimmen.** Beispielsweise überlappende Polygonanteile,
  bei denen die Vereinigung eine kleinere Fläche hätte, bleiben ein
  Fehler; kein verdeckter positiver Flächenverlust.
- Auch sehr kleine positive Polygonflächen bleiben erhalten,
  ausdrücklich **auch für Klasse 25**.
- Das original extrahierte GeoPackage und die Feature-ID bleiben
  unverändert. Jedes normalisierte Objekt wird unter
  fmzk_geometrieereignisse mit Status
  polygonanteile_aus_geometrycollection, FID, FMZK-Klasse,
  den ursprünglichen Geometrietypen und beiden Flächenzahlen
  dokumentiert. Reparaturen ungültiger Geometrie und flächenlose
  Zuschnittreste werden weiterhin gesondert gezählt.
- Es erfolgt **keine neue FMZK-Extraktion** und kein allgemeines
  Unterdrücken von Geometriefehlern.

Zur Prüfung vor der Fortsetzung:

~~~bash
git pull --ff-only
.venv/bin/python -m unittest discover -s tests \
	-p 'test_analyze_street_space.py' -v
.venv/bin/python -m unittest discover -s tests \
	-p 'test_analyze_kataster.py' -v
.venv/bin/python -m unittest discover -s tests \
	-p 'test_wienwide_kataster.py' -v
bash scripts/run-wien-gartenstrassen.sh --from inputs --until inputs
~~~

Die reale Geometrie von FID 782170 liegt weiterhin nur im
lokalen Cache. Sollte ihre Polygonanteilsbilanz abweichen, hält
der neue Check mit Flächendifferenz ausdrücklich an; ohne diesen
Befund wird kein Quellkonflikt wegkorrigiert.

## Dichte Kataster-Kachel mit mehr als 1500 Kern-Treffern (16.10.2026)

Der laufende Wiener Eingabedurchgang verarbeitete
x-000006_y+000335 mit **9785 FMZK-Features** und **689**
vom Kern getroffenen Grundstücken. Die nächste Kachel
x-000005_y+000335 enthielt **18673 FMZK-Features**; ihre
BEV-z16-Auswahl umfasst **1587 Kerngrundstücke**, bei
ursprünglich maximal **1500** zulässigen Treffern.

Dies ist eine absichtliche Ressourcenschutzgrenze, **kein
Geometrie- oder Katasterfehler**. Da die Wiener
1-km-Rasterkacheln mit 75-m-Halo bereits festliegen, kann der
einzelne Ausschnitt nicht ohne Wechsel der Rastermethodik
verkleinert werden.

Ausschließlich scripts/run-wien-gartenstrassen.sh übergibt
für die Wien-Phase inputs künftig **maximal 2500** an
scripts.wienwide_street fetch-inputs; der allgemeine
Kataster-Pilot bleibt bei **250**. Bestehende räumliche
und BEV-Kachel-Grenzen bleiben unverändert. Die Option
--details bleibt ausgeschaltet, sodass daraus **keine neuen
Grundstücksdetail-API-Anfragen** entstehen. Falls eine weitere
Wien-Kachel auch 2500 überschreitet, stoppt die Analyse weiterhin
vor der Detail- und Ergebnisphase mit einem überprüfbaren
Fehler. Keine unbegrenzte Verarbeitung.

Nach dem Pull wird derselbe geprüfte lokale FMZK-Zuschnitt
der unterbrochenen Kachel verwendet; die bereits
fertigen Katasterberichte werden nicht neu berechnet:

~~~bash
git pull --ff-only
.venv/bin/python -m unittest discover -s tests \
	-p 'test_analyze_kataster.py' -v
bash scripts/run-wien-gartenstrassen.sh --from inputs --until inputs
~~~

Die reale Verarbeitung der 1587 Grundstücke sowie aller weiteren
Wien-Kacheln ist nach Änderung des Limits **noch nicht verifiziert**.

## Pfade und Parameter

| Element | Standard |
| --- | --- |
| AOI | data/raw/bezirke-wien/wien.geojson |
| FMZK | data/raw/FMZK_WIEN_GP.gpkg |
| Analyse | data/processed/wienweit/wien/ |
| Raster | 1000 m, Halo 75 m |
| GIP-V0 | Stützpunkte 5 m, Knotenradius 7 m, maximaler Achsabstand 25 m, regulär FOW=3 |
| Kataster | 2500 vom FMZK-Kern getroffene Grundstücke je Wien-Analysekachel als explizites technisches Schutzlimit (lokaler Pilot weiterhin 250) |
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
