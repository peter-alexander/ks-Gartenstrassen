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

## Metrische BEV-nfl-Masken mit nur einer Nutzungsgruppe (16.10.2026)

Nach vollständigem Abschluss der 489 Wiener Eingabekacheln wurde
die Phase street gestartet. Die Straßenraum-Vorstufe erreichte
Kachel 79/489; unmittelbar danach meldete der metrische
BEV-z16-Reader: "BEV-nfl benötigt Straßen- und sonstige
Nutzungsflächen". Die genaue Kachel-ID der gescheiterten
Folgekachel wurde im Fehlerlog nicht ausgegeben.

Der Reader hatte bisher **beide** Gruppen als zwingende Bedingung
geprüft. Fachlich sind aber auch nur eine Gruppe enthaltende
Katasterausschnitte zulässig. Unter Beibehaltung der
ursprünglichen Straßenraumklassifikation gelten daher:

- BEV-nfl 95/65 vorhanden, sonstige nfl fehlen: die
  Straßenmaske wird vollständig gelesen; die sonstige Maske ist
  ein gültiges leeres Polygon. Nicht-Kern-FMZK-Flächen werden
  weiterhin nur bei mindestens 95 Prozent 95/65-Deckung und
  höchstens 5 Prozent Gegenbelegung zugeordnet.
- Sonstige BEV-nfl vorhanden, 95/65 fehlen: die BEV-Straßenmaske
  ist ein gültiges leeres Polygon. FMZK-Kernklassen
  21/23/24/25/33/39 bleiben nach V0 trotzdem Straßenraum;
  ohne 95/65-Nachweis werden keine zusätzlichen Nicht-Kernflächen
  positiv klassifiziert.
- **Beide Gruppen fehlen** nach Auswahl der nachgewiesenen
  Kerngrundstücke und Anwendung der bisherigen
  0,05-m²-Fragmentgrenze: weiterhin **Abbruch** mit einer
  aussagekräftigen Meldung. Keine unbelegte Nullmaske.
- Die komplette BEV-Kachelliste und der Offline-Rohdaten-Cache
  werden unverändert verifiziert, unbekannte Nutzungscodes führen
  weiterhin zum Abbruch. Der Bericht des Straßenraumkachel-Caches
  enthält künftig nfl_gruppenstatus, nfl_strassenfragmente und
  nfl_sonstige_fragmente neben allen Rohdatenprüfsummen.
- Die FMZK-Regelversion, die 95-Prozent-Schwelle und die
  Bearbeitung vorhandener Kachelergebnisse ändern sich nicht.
  Auch bestehende erfolgreich erstellte street.sqlite-Dateien
  werden weiterhin nur nach erneuter Provenienzprüfung verwendet.

Tests für beide einseitigen Fälle, den weiter gültigen positiven
Klassennachweis sowie für völlig fehlende und ausschließlich
unterhalb der Flächenschwelle liegende nfl-Fragmente liegen in
tests/test_wienwide_kataster.py.

~~~bash
git pull --ff-only
.venv/bin/python -m unittest discover -s tests \
	-p 'test_wienwide_kataster.py' -v
bash scripts/run-wien-gartenstrassen.sh --from street --until street
~~~

Ein vollständiger realer Wien-Straßenraumlauf nach dieser Änderung
ist noch nicht bestätigt.

## Topologisch ungültige BEV-nfl-Vereinigung (16.10.2026)

Nach abgeschlossenem Wien-Inputlauf (489/489) erreichte die
Straßenraumphase **113/489**; die folgende Kachel stoppte mit
"Metrische BEV-nfl-Vereinigung ungültig". Die konkrete Kachel
kann aus der bisherigen Logzeile noch nicht eindeutig benannt werden,
da die Fehlermeldung bisher keine Kachel-ID enthielt.

Jedes BEV-nfl-Quellfragment wurde nach der unveränderten
0,05-m²-Schwelle schon einzeln auf Polygonalität und Gültigkeit
geprüft. Der Abbruch entstand erst, nachdem die Fragmente je
Nutzungsgruppe (95/65: Straße; andere Codes: sonstige)
zu einer Gesamtmaske vereinigt wurden.

Die Reparatur erfolgt ausschließlich, **falls diese Gesamtmaske
topologisch ungültig ist**:

- Der GEOS-Gültigkeitsfehler wird ermittelt. Ein einziges
  make_valid auf der ungültigen Union ist erlaubt, gefolgt
  von der Übernahme ihrer polygonalen Bestandteile.
- Die Fläche vor und nach der Reparatur darf sich höchstens um
  **max(0,01 m², 10⁻⁸ × Ausgangsfläche)** unterscheiden.
- Unabhängig von dieser Summenprüfung muss die neue Maske
  **jedes einzelne originale, gültige Quellfragment** vollständig
  innerhalb derselben Flächentoleranz überdecken. Auch ein
  geometrisch verschobener gleich großer Polygonumriss kann
  dadurch nicht unbemerkt durchgehen.
- Mehr als diese rein numerische Flächentoleranz verlorene oder
  zusätzliche Fläche und nicht reparierbare Polygone führen
  weiterhin zum Abbruch. Kein unkontrolliertes buffer(0),
  keine Generalisierung und keine neuen Online-Downloads.
- Erfolgreiche Reparaturen werden als
  kataster_status.nfl_vereinigungsreparaturen mit BEV-Gruppe,
  GEOS-Befund, Quellfragmentzahl, alter/neuer Fläche,
  Differenz, geprüfter nicht abgedeckter Fläche und Toleranz
  in der Straßenraumkachel dokumentiert.
- Die weiterhin bestehende originale Quell-PBF-Prüfsumme,
  FMZK-Klassifikation, 95-%-Zuordnung sowie bestehenden
  SQLite-Kacheln bleiben unverändert. Künftige
  Fehlermeldungen im Street-Build enthalten die Kachel-ID.

Vor der Fortsetzung:

~~~bash
git pull --ff-only
.venv/bin/python -m unittest discover -s tests \
	-p 'test_wienwide_kataster.py' -v
bash scripts/run-wien-gartenstrassen.sh --from street --until street
~~~

Die echte ungültige BEV-Union kann nur der lokale Lauf prüfen.
Falls die Flächenbilanz nicht erhalten werden kann, erscheint
eine präzisere Fehlermeldung mit Gruppe und Abweichung;
in diesem Fall keine weitere automatische Reparatur.

## GEOS-Ausnahme schon während der BEV-Union (16.10.2026)

Die Wiener Straßenraumphase erreichte **239/489**. Danach brach die
GEOS-Vereinigung noch vor der bisherigen Gültigkeitskontrolle ab:

> TopologyException: Ring edge missing at 10091.849205025215 340087.48499677476

Die erste Reparatur der ungültigen, aber bereits erzeugten Union
(Kachel 114; GEOS: Nested shells) war dagegen erfolgreich und
wurde mit maximal 0,000002 m² nicht abgedeckter Quellfläche protokolliert.
Die FMZK-Kleinstreste bei Kacheln 194 und 220 wurden ebenfalls
regelkonform mit Quell-ID dokumentiert.

**Neuer, ausschließlich bei GEOSException aktiver Schutzpfad:**

- Zunächst bleibt die exakte union_all-Vereinigung unverändert.
- Scheitert sie durch einen GEOS-Topologiefehler, werden feste
  Precision-Grid-Größen von 1e-9, 1e-8, 1e-7 und 1e-6 Metern
  nacheinander getestet. Die Quellen selbst werden nicht verändert.
- Jeder mögliche Ersatz muss ein gültiges Polygon ergeben. Nur wenn
  erforderlich, greift zusätzlich die bereits vorhandene Prüfung
  einer make_valid-Reparatur.
- **Quellabdeckung:** Jedes Originalfragment wird mit difference
  gegen den Ersatz geprüft. Der gesamte fehlende Flächenanteil darf
  maximal max(0,01 m², 1e-8 × Maskenfläche) betragen.
- **Zusatzflächenkontrolle:** Von der Ersatzmaske werden die
  ursprünglichen Polygonfragmente in Blöcken abgezogen. Falls ein
  Block ebenfalls eine GEOS-Ausnahme auslöst, wird er rekursiv
  halbiert bis zu den einzelnen Quellfragmenten. Eine verbleibende
  nicht belegte Fläche über der gleichen Toleranz führt zum Abbruch.
- Unterhalb der 0,05-m²-Schwellengröße verworfene Rohfragmente
  bleiben ausgeschlossen; **beibehaltene sehr dünne positive
  Flächen dürfen nicht durch die Reparatur verloren gehen**.
- Nur ein vollständig nachgewiesener Kandidat wird ausgegeben und
  als nfl_vereinigungsreparaturen mit ursprünglichem GEOS-Fehler,
  Nutzungsgruppe, Grid, Toleranzen und beiden Abweichungsflächen
  in der Straßenraum-Metadatenbank dokumentiert.
- Fehlgeschlagene Versuche werden **nicht** als Ergebnis gespeichert;
  sie führen zu einem ValueError mit Kachel-ID, Nutzungsgruppe und
  allen getesteten Präzisionsstufen. Die 239 bereits erstellten
  Kacheln und alle 489 FMZK-/BEV-Eingaben bleiben bestehen.

Nach dem Pull zunächst nur die Tests und die Phase street starten:

~~~bash
git pull --ff-only
.venv/bin/python -m unittest discover -s tests \
	-p 'test_wienwide_kataster.py' -v
bash scripts/run-wien-gartenstrassen.sh --from street --until street
~~~

Die Wirkung für die konkrete Originalgeometrie mit Ring-edge-missing
ist **noch nicht lokal bestätigt**.
## Voronoi-Overlay bei GIP 10466577 (16.10.2026)

Nach erfolgreichem Abschluss der Wiener Straßenraumphase (489/489)
verarbeitete die Partition **469 von 489** Kacheln bis einschließlich
x+000007_y+000350. Die nächste Kachel brach mit
**Voronoi 10466577: ungültige polygonale Fläche** ab.
Der Fehler trat nach Berechnung einer GIP-bezogenen Voronoi-Fläche
auf, nicht beim Download oder beim Straßenraumaufbau.

Vorher gab die Polygonvalidierung auch bei **geringfügigen
topologischen Overlay-Artefakten** sofort einen Fehler aus.
Die neue Behandlung ist bewusst enger als eine allgemeine
Bereinigung von GIP-Geometrien:

- Eine gültige Fläche wird unverändert übernommen.
- Nur falls ein **nach dem Overlay** erzeugtes Polygon
  topologisch ungültig ist, wird shapely.make_valid auf dessen
  polygonalen Bestandteile angewandt. Fehlende oder ungültige
  Nullflächen werden nicht stillschweigend als leer akzeptiert.
- Vorher-/Nachher-Flächen müssen bis auf höchstens
  max(0,01 m², 1e-8 × Ausgangsfläche) übereinstimmen.
- Insbesondere bei einem Voronoi-Zuschnitt muss die reparierte
  Fläche weiterhin **innerhalb der Voronoi-Zellen der GIP-Achse**
  und **innerhalb des noch nicht zugeordneten Straßenraums** liegen.
  Analog bleiben reparierte Achsabstands- und Exklusiv-Schnitte
  in beiden ursprünglichen Schnittpartnern.
- Eine großflächige Selbstüberschneidung, ein größerer Flächenverlust
  oder eine Verletzung dieser Herkunftsgrenzen führen zum Abbruch.
- Jede erfolgreiche Reparatur wird im stats_json der
  SQLite-Tabelle tiles unter geometrie_reparaturen mit GIP-ID,
  GEOS-Befund, Ausgangs-/Ergebnisfläche, Flächendifferenz,
  geprüften Außenseitenflächen und Toleranz protokolliert.
- Die bestehende Kachel-Flächenbilanz prüft weiterhin
  Überlagerung, Fehlfläche und Fläche außerhalb der Straßenmaske.
  GIP-Zuordnung, FOW=3, Stützpunktabstand 5 m, Knotenradius 7 m,
  Achsabstand 25 m und das globale Site-Verzeichnis bleiben gleich.

Die bereits erstellten 469 Partitionsergebnisse bleiben in
data/processed/wienweit/wien/aufteilung.sqlite und werden bei
der Fortsetzung nur nach unveränderten Straßenraum-Quellprüfsummen
wiederverwendet. Die 489 street.sqlite-Eingaben bleiben unverändert.

~~~bash
git pull --ff-only
.venv/bin/python -m unittest discover -s tests \
	-p 'test_wienwide_pipeline.py' -v
bash scripts/run-wien-gartenstrassen.sh --from partition --until partition
~~~

Die echte Voronoi-Geometrie 10466577 ist nur im lokalen Wiener
Cache verfügbar; die Reparaturwirkung dort ist noch nicht
nachgewiesen. Sollte die Flächentreue nicht gesichert sein,
bricht der Lauf weiterhin mit einer präziseren Meldung ab.
## Voronoi-GIP 10466577: unzulässiger Ausgriff nach make_valid (16.10.2026)

Bei Wiederaufnahme der Partition stoppt die Kachel
**x+000008_y+000350** nach 469 erfolgreich gespeicherten Kacheln:

> Voronoi 10466577: Reparatur liegt um 1200,880698 m² außerhalb
> noch nicht zugeordneter Straßenraum; Nested shells

Die Sicherheitsprüfung hat korrekt verhindert, dass eine
ungültige GEOS-Schnittgeometrie mittels make_valid zu einer
flächenmäßig ähnlichen, aber **örtlich falsch zugeordneten**
Voronoi-Fläche wird. Eine Erhöhung der Toleranz oder blindes
Abschneiden wäre hier fachlich unzulässig.

**Neuer enger Wiederherstellungsweg in der Partition:**

- Die bisherige exakte Schnittoperation auf der Vereinigung
  der Voronoi-Zellen bleibt unverändert die erste Wahl.
- Nur bei Topologie-/Validierungsfehlern wird die Schnittfläche
  **neu aus den ursprünglichen Voronoi-Einzelzellen** erzeugt.
  Jede Einzelzelle wird separat mit dem noch unzugeordneten
  Straßenraum geschnitten; danach werden die gültigen
  Polygonanteile vereinigt.
- Erst falls der Einzelzellenweg scheitert, werden dieselben
  ursprünglichen, gültigen Ausgangsflächen mit Precision-Grids
  von 10^-9 bis 10^-6 m geschnitten. Es gibt keine pauschale
  Quellrundung, keine neuen GIP-Stützpunkte und keine andere
  Straßenraumregel.
- **Vollständigkeitsbeweis für jedes Alternativergebnis:**
  Es darf weder Fläche außerhalb der zugehörigen Voronoi-Zellen
  noch außerhalb der verfügbaren Straßenmaske entstehen.
  Gleichzeitig muss auch jede Fläche ihrer tatsächlichen
  geometrischen Schnittmenge im Alternativergebnis enthalten
  sein. Beide Arten von Abweichungen werden mit derselben
  numerischen Toleranz max(0,01 m², 10^-8 × kleinere
  Ausgangsfläche) getrennt getestet.
- Jeder erfolgreiche Ersatz wird als geometrie_reparaturen
  im SQLite-Kachelbericht mit GIP-ID, Originalfehler, Methode,
  Zellenzahl, etwaigem Precision-Grid und allen vier
  Differenzflächen dokumentiert.
- Kann die Vollständigkeit nicht nachgewiesen werden, bleibt
  die Kachel ausdrücklich ungeschrieben; die Fehlermeldung
  enthält die Gründe aller fehlgeschlagenen Alternativen.

Die bestehenden 469 Partitionsergebnisse in aufteilung.sqlite,
alle 489 Street-Kacheln, der GIP-Index und sämtliche Originalquellen
bleiben unverändert. Tests decken akzeptierte exakte
Einzelzellenrekonstruktion, abgewiesene fehlende oder zusätzliche
Fläche, Precision-Fallback und normalen unveränderten Betrieb ab.

~~~bash
git pull --ff-only
.venv/bin/python -m unittest discover -s tests \
	-p 'test_wienwide_pipeline.py' -v
bash scripts/run-wien-gartenstrassen.sh --from partition --until partition
~~~

Die reale GEOS-Geometrie dieser Kachel ist weiterhin nur
im lokalen Wien-Cache vorhanden. Falls beide Rekonstruktionswege
scheitern, ist die nächste Maßnahme eine gezielte Quellgeometrie-
diagnose, nicht das Aufweichen der Flächenprüfungen.
## Diagnose der systematisch fehlenden Voronoi-Fläche (16.10.2026)

Die Wiederaufnahme von partition an Kachel x+000008_y+000350
und GIP 10466577 zeigte: Der direkte Schnitt lieferte eine
topologisch ungültige Geometrie (Nested shells); make_valid
würde um 1200,880698 m² aus dem verfügbaren Straßenraum
hinausgreifen. Der explizite Einzelzellen-Weg sowie alle
Präzisionsstufen von 10^-9 bis 10^-6 m sind ebenfalls um
ca. 1200,880845 m² **unvollständig**. Die Abweichung ist
praktisch unabhängig vom Präzisionsraster und kann nicht als
Rundungstoleranz behandelt werden. Der harte Abbruch ist richtig.

Vor einer weiteren fachlichen Geometriekorrektur steht nun eine
**reproduzierbare lokale Diagnose aus den bestehenden Caches**.
Sie hält die tatsächliche verbleibende Straßenmaske exakt nach
den bereits abgearbeiteten GIP-Achsen fest, gemeinsam mit allen
Einzel-Voronoi-Zellen der konkreten Achse und deren Union.
Die produktive Partitionierung und aufteilung.sqlite werden
nicht verändert; auch GIP-Index und Street-Original-WKB bleiben
unangetastet.

~~~bash
git pull --ff-only
.venv/bin/python -m unittest discover -s tests \
	-p 'test_wienwide_pipeline.py' -v
.venv/bin/python -m scripts.diagnose_wien_voronoi \
	--tile-id x+000008_y+000350 \
	--gip-id 10466577 \
	--out data/processed/wienweit/wien/diagnose-voronoi-10466577.zip
~~~

Das ZIP speichert native EPSG:31256-WKB-Geometrien als
wkb/*.wkb und diagnose.json: ursprüngliche Voronoi-Einzelzellen,
deren Vereinigung, den echten vorverteilten Straßenraumrest,
direkten Schnitt, separate Einzelschnitte, numerische
Präzisionsschnitte und die ermittelten Fehlflächen.
Die Diagnose listet außerdem flächenmäßig auffällige
Einzelzellen und Quellprüfsummen. Sie ist auf genau diesen
einen GIP-Abschnitt und diesen einen Kachelzustand begrenzt.

Erst anhand dieses konkreten geometrischen Befunds wird
entschieden, ob der Fehler schon in einer Voronoi-Einzelzelle,
der gruppierten Zellenvereinigung, der Restmaske oder einer
GEOS-Overlay-Operation entsteht. Es werden weder Quellbereiche
still verworfen noch 1200 m² pauschal neu zugeordnet.
## Nachweis: GEOS-Overlay-Geometrie am Persidisweg (16.10.2026)

Die hochgeladene originale Diagnose
diagnose-voronoi-10466577.zip zur Kachel
x+000008_y+000350 (GIP 10466577, Persidisweg, EPSG:31256)
ermöglicht eine **reproduzierbare** Erklärung:

| Originalgeometrie | Fläche |
| --- | ---: |
| Restmaske nach früheren GIP-Zuordnungen | 2.096,260363 m² |
| Vereinigte sieben gültige Voronoi-Zellen | 1.200,880845 m² |
| Summe ihrer sieben einzelnen gültigen Schnitte mit Restmaske | 0,000146955 m² |
| Ungültiger direkter GEOS-Gesamtschnitt (Nested shells) | 1.200,880992 m² |

Beide **Ausgangsgeometrien sind gültig**. Der ungerasterte
GEOS-Gesamtschnitt verletzt jedoch die Mengeneigenschaften:
Seine angebliche 1200-m²-Fläche befindet sich großteils
außerhalb der Restmaske. Auch die vorherige vermeintlich
unabhängige Kontrollformel
`(owner_cells - candidate).intersection(remaining)`
lieferte dieselben rund 1.200,88 m² fälschlich als fehlend.
Das war ein **zweiter GEOS-Overlay-Fehler im Kontrollweg**,
nicht der Verlust dieser Fläche in der Einzelzellenrekonstruktion.

**Geprüfte Korrektur:** Nur wenn der normale direkte Schnitt
scheitert, wird weiterhin die ungerundete Einzelzellen-
Rekonstruktion verwendet. Ihre Vollständigkeit wird
nun mithilfe **zweier fein gerasterter Kontrollschnitte**
(1e-9 und 1e-8 Meter) und zweier eigenständiger
Quellflächenbilanzen überprüft:

- Fläche A = (A minus B) + (A Schnitt B)
- Fläche B = (B minus A) + (A Schnitt B)

Der Ersatz muss beide Kontrollschnitte geometrisch abdecken
und darf darüber hinaus keine relevante Zusatzfläche haben.
Beide Prüfraster müssen sich untereinander einig sein.
Die zulässige Abweichung ist für echte Kleinstflächen
nun bis auf 1e-8 m² reduziert, statt sie unbemerkt unter
der vorherigen pauschalen 0,01-m²-Grenze zu verwerfen.
Fehlt dieser Nachweis, stoppt die Partition wie bisher.
Die vollständigen Prüfzahlen der beiden Raster landen im
SQL-Metadatenfeld geometrie_reparaturen.

**Wichtig:** Die Diagnose-ZIP selbst wird **nicht** ins
Repository eingecheckt. Der optionale Regressionstest
verwendet nur die schon lokal vorhandene ZIP:

~~~bash
git pull --ff-only
WIEN_VORONOI_DIAG_ZIP=data/processed/wienweit/wien/diagnose-voronoi-10466577.zip \
	.venv/bin/python -m unittest discover -s tests \
	-p 'test_wienwide_pipeline.py' -v
bash scripts/run-wien-gartenstrassen.sh --from partition --until partition
~~~

Die echte WKB-Geometrie wurde separat in einer
Shapely-2.1.2/GEOS-3.13.1-Umgebung reproduziert und
mit beiden Kontrollrastern geprüft. Ob der vollständige
lokale Wiener Partitionierungslauf nach dieser Änderung
erfolgreich endet, ist noch nicht bestätigt.
## Wienweiter GRM-GetMap-Abruf: Umfangskontrolle (16.10.2026)

Nach erfolgreichem Abschluss von street, partition und qa mit
jeweils 489/489 Kacheln stoppte grm-fetch **vor dem ersten Abruf**:

> Fehler: Zu viele WMS-Anfragen: kleinere AOI verwenden

Ursache war die doppelte Nutzung von MAX_CHUNKS=1200:
einmal **je Rasterkachel** (Sicherheitslimit) und versehentlich
noch einmal als **globales Limit** für den gesamten Wien-Lauf.
Eine 1000-m-Rasterkachel wird in maximal vier GetMap-Bilder
zu 500 × 500 m bei 0,5 m/Pixel unterteilt; bei 489 Kacheln
sind theoretisch bis zu 1956 Bilder vorgesehen. Am Wiener
Außenrand können vollständige 500-m-Teilbilder entfallen.

**Korrektur:** Die globale Schranke entfällt. Weiterhin gelten:

- höchstens MAX_CHUNKS GetMap-Teilbilder **je** Analyse-Kachel;
- gültige metrische 0,5-m-Pixelraster und maximal 2048 × 2048
  Pixel beziehungsweise 3.000.000 Pixel je Teilbild;
- maximal 15 MB GetMap-Antwort je Abruf;
- PNG-Format und Pixelabmessungen müssen dem Abruf entsprechen;
- geordnete, vollständige AOI-Kernabdeckung je Analyse-Kachel;
- getrennte PNG+JSON-Caches mit Rasterparametern, GetMap-URL
  und SHA-256 jeder Quelldatei; bestehende Caches werden
  streng geprüft und nie still überschrieben;
- 0,5 Sekunden Pause **zwischen tatsächlichen neuen GetMap-Abrufen**;
- Wiederaufnahme nach Unterbrechung ohne erneutes Laden bereits
  geprüfter PNG-Dateien.

Vor dem Herunterladen gibt das Programm die geplante Gesamtzahl
der WMS-Bilder aus. Die Anzahl allein wird nicht mehr als
vermeintlicher Hinweis auf ein zu großes Arbeitsgebiet gewertet.
Ein neuer Offline-Test prüft drei synthetische Kacheln gegen
ein künstliches Gesamtlimit von zwei Bildern und bestätigt
Cache-Reuse und weiterhin strenge Einzelkachelgrenzen.

~~~bash
git pull --ff-only
.venv/bin/python -m unittest discover -s tests \
	-p 'test_wienwide_grm2023.py' -v
bash scripts/run-wien-gartenstrassen.sh --from grm-fetch --until grm-fetch
~~~

Die wienweite Datenabdeckung ist erst bestätigt, nachdem
**grm-fetch** vollständig beendet ist und anschließend
**grm-build** sämtliche Original-PNGs einschließlich der
neun RGB-Klassen auf Gültigkeit geprüft hat.
## GRM2023-WMS: transparenter Hintergrund an Wiengrenze (16.10.2026)

Der GRM-WMS-Download wurde für ganz Wien mit
489 Rasterkacheln und **1816 von 1816 geprüften PNG-Caches**
abgeschlossen. Beim ersten Versuch von `grm-build` stoppt
der Teilbild-Decoder an
`x-000009_y+000331/x000_y001` mit
`(255, 255, 255, 0)` für 753382 Pixel.

Der GetMap-Request setzt ausdrücklich
`transparent=TRUE` und `bgcolor=0xFFFFFF`. Ein **vollständig
transparentes weißes Pixel** bedeutet daher einen
**nicht gezeichneten WMS-Hintergrund**, keine GRM-Fachklasse.
Da die rechteckigen 500-m-Bildkacheln die tatsächliche
Wiener AOI überragen können, sind solche Pixel **außerhalb**
der Wiener Stadtgrenze erwartbar.

**Neue strenge Decodierung in der Wien-Pipeline:**

- Die bisherigen neun RGB-Fachklassen bleiben ausschließlich
  mit Alpha 255 zulässig. Die Baumschicht bleibt exakt
  `#38A800` mit Alpha 255.
- Vollständig transparente weiße Pixel `(255,255,255,0)`
  sind **nur außerhalb der eigentlichen Wiener AOI** erlaubt.
  Die 0,5-m-Pixelzellen werden geometrisch als vollständige
  Flächenrechtecke mit der Wiener Grenze verschnitten;
  auch Randzellen mit nur anteiliger Überdeckung werden
  geprüft. Ein bloßer Pixelmittelpunkttest genügt nicht.
- Ein transparentes Pixel mit positiver Fläche innerhalb
  der AOI bleibt ein **harter Fehler** (mögliche GRM-Datenlücke).
  Es wird weder als „keine Bäume“ klassifiziert noch
  künstlich mit einer der neun Klassen gefüllt.
- Alpha 1–254, Alpha 0 mit anderer RGB-Farbe und unbekannte
  deckende RGB-Farben bleiben wie bisher unzulässig.
- Der Decoder verlangt beim Vorliegen von Transparenz
  die gültige echte AOI. Im erzeugten Masken-SQLite wird
  die Anzahl der **transparenten Pixel außerhalb AOI**
  separat protokolliert.
- Schon heruntergeladene PNGs und ihre SHA-256-Metadaten
  bleiben unverändert; es erfolgt **kein erneuter WMS-Abruf**.
  Bereits erstellte und geprüfte GRM-Kachelmasken werden
  ebenfalls wiederverwendet.

Die neue Prüfung ist in Offline-Tests für WMS-Hintergrund
außerhalb Wien, Datenlücken innerhalb Wien, nur anteilig
angeschnittene Randpixel und unbekannte Alpha/RGB-Farben
abgedeckt.

~~~bash
git pull --ff-only
.venv/bin/python -m unittest discover -s tests \
	-p 'test_wienwide_grm2023.py' -v
bash scripts/run-wien-gartenstrassen.sh --from grm-build --until grm-build
~~~

Falls der betreffende WMS-Teilbildbereich tatsächlich
transparente Pixel **innerhalb der Stadtgrenze** enthält,
stoppt der Bau ausdrücklich erneut mit der entsprechenden
Zeile/Pixelnummer. Vor einer Klassenzuordnung muss die
GRM-WMS-Abdeckung dann fachlich geklärt werden.
## Export: metrisch gültige, aber nach WGS84 ungültige GIP-Geometrie (16.10.2026)

Der Wien-Gesamtlauf hat die 489 GRM-Maskenkacheln und danach die
vollständige abschnittsbezogene Begrünungsmessung für **24.937**
FOW=3-GIP-IDs erfolgreich abgeschlossen: 36.304.778,546 m²
Abschnittsfläche, davon 3.076.089,652 m² Bodenbegrünung (8,473 %)
und 4.541.527,726 m² WMS-Baumschicht (12,509 %).

Der anschließende 100-m²-GeoJSON-Export meldete für
**GIP 10023274**: `WGS84-Geometrie ungültig`.
Zu diesem Zeitpunkt war die ursprüngliche, nach GIP-ID
vereinigte Geometrie im metrischen **EPSG:31256 bereits
gültig und flächenbilanziert**. Der Fehler trat erst durch
die Transformation zu **EPSG:4326** auf.

Bei Polygongrenzen mit vielen kurzen Segmenten kann eine
rechnerische Transformation ungültige Ringtopologie
erzeugen. Ohne die Original-WKB von GIP 10023274 ist die
genaue GEOS-Ursache noch nicht nachgewiesen. Deshalb wird
der Quellraum nicht verändert und es gibt keine pauschale
make_valid-Behandlung ohne Nachweis.

**Geändertes Exportverfahren:**

- Gültiges WGS84 bleibt exakt so wie bisher.
- Nur bei ungültigem WGS84: Reparatur der polygonalen
  Bestandteile der **Publikationsgeometrie** mit make_valid.
  GIP-Abschnitte, Flächenmetriken und das Quell-GeoPackage
  bleiben unverändert.
- Rücktransformation in EPSG:31256 und Vergleich mit
  der ursprünglich gültigen, vollständig vereinigten GIP-Geometrie.
- Die korrigierte Geometrie muss gültig, nicht leer und
  metrisch flächentreu sein: zulässige Gesamtflächenänderung
  max(0,01 m², 10^-6 × Abschnittsfläche).
- Zusätzliche und fehlende Flächen werden unabhängig
  anhand von Geometrie-Differenzen geprüft. Je zulässig
  höchstens max(0,01 m², 0,003 m × ursprüngliche Grenzlänge).
  Die längenbezogene Komponente berücksichtigt die auch
  bei gültigem Hin-/Rücktransformieren unvermeidliche
  Millimeterabweichung an jeder Grenzkante.
- Die maximale Verschiebung der metrischen Grenzlinien
  darf **0,01 m** nicht überschreiten.
- Jede freigegebene WGS84-Korrektur wird mit GIP-ID,
  GEOS-Gültigkeitsfehler, fehlender/zusätzlicher Fläche,
  Grenzverschiebung und Toleranzen im
  `export_bericht.json` unter `wgs84_projection_repairs`
  protokolliert; auch die Anzahl wird ausgewiesen.
- Wenn irgendeine Prüfung nicht bestanden wird,
  bricht der Export weiter ab und verwirft seine
  temporäre Ausgabe. Bereits fertige Eingaben bleiben erhalten.

Regressionstests prüfen akzeptierten, flächentreuen
Randkantenfehler, unveränderte gültige Geometrie,
verbotene Verschiebung und großen Flächenverlust.

~~~bash
git pull --ff-only
.venv/bin/python -m unittest discover -s tests \
	-p 'test_wienwide_result_export.py' -v
bash scripts/run-wien-gartenstrassen.sh --from export --until export
~~~

Die reale Wirkung auf GIP 10023274 ist erst durch
die lokalen Originalgeometrien beim erneuten Export bestätigt.
## WGS84-Export: erneute Ungültigkeit erst beim Rückprojektions-Check (16.10.2026)

Nach Einführung der streng geprüften WGS84-Ausgabereparatur
stoppt die Wien-Ausgabe bei **GIP 10023323**:

> WGS84-Geometrie ungültig
> (Too few points in geometry component[16.2140370087171 48.2445637429625]);
> metrische Reparaturprüfung fehlgeschlagen: Rückprojektion nicht gültig

Die zuerst ausgeführte WGS84-Reparatur erzeugte dabei eine
gültige Publikationsgeometrie; **die nur zur Flächenkontrolle
zurückprojizierte Geometrie** wurde anschließend ungültig.
Insbesondere sehr kurze Ringsegmente können beim zweimaligen
Transformieren zu kollabierten Ringen führen. Ohne vollständige
Original-WKB ist die genaue lokale Teilfläche noch nicht
nachgewiesen.

**Abgesicherte Kontrolle (keine Änderung an Fachgeometrien):**

- Der originale gültige EPSG:31256-Abschnitt wird nicht
  verändert. Die bereits gültige WGS84-Ausgabegeometrie
  wird durch diesen Zusatz ebenfalls nicht verändert.
- **Nur wenn die zurückprojizierte Prüfgeometrie** ungültig
  ist, wird für die Kontrolle ihr gültiger polygonaler
  Bestandteil mit `make_valid` wiederhergestellt.
- Schon der Verlust oder Zugewinn von Fläche durch diese
  Wiederherstellung muss unter
  `max(0,01 m², 10^-6 × Originalabschnittsfläche)` bleiben;
  andernfalls gilt die Kontrolle als fehlgeschlagen.
- Anschließend bleiben ALLE bestehenden Prüfungen erhalten:
  Gesamtfläche, fehlende/zusätzliche Flächen, metrische
  Grenzverschiebung höchstens 1 cm. Nicht gültige oder
  nicht polygonale Rekonstruktionen werden abgelehnt.
- Im Exportbericht werden zusätzlich der GEOS-Grund der
  ungültigen Rückprojektion und deren Reparatur-Flächendifferenz
  unter `wgs84_projection_repairs` festgehalten.

Regressionstests reproduzieren eine ungültige Kontrollprojektion
mit `Too few points`, lehnen eine räumlich verschobene
Kontrollprojektion ab und verwerfen eine
nichtpolygonale Rückprojektionsreparatur.

~~~bash
git pull --ff-only
.venv/bin/python -m unittest discover -s tests \
	-p 'test_wienwide_result_export.py' -v
bash scripts/run-wien-gartenstrassen.sh --from export --until export
~~~

Der Erfolg für die reale Geometrie `10023323` ist erst
nach dem lokalen erneuten Test und Export bestätigt.
## Export-GIP 10023323: 29,6 cm Grenzabweichung – keine automatische Freigabe

Der erneute Wiener Publikationsexport stoppt bei GIP `10023323`
nach erfolgreicher WGS84- und Rückprojektionskontroll-Reparatur:

~~~text
WGS84-Geometrie ungültig (Too few points in geometry component
[16.2140370087171 48.2445637429625]);
Flächenänderung +0.000002585 m² (max 0.010000),
zusätzlich 0.061854795 m², fehlend 0.061852210 m²
(je max 0.694120),
Grenzverschiebung 0.296424 m (max 0.010)
~~~

Die fast exakt gleiche Fläche beweist **nicht** die räumliche
Übereinstimmung. 29,6 cm maximale Grenzabweichung überschreiten
die bisherige Schranke um etwa Faktor 30. Daher bleibt die
Ausgabe bewusst blockiert. Weder Grenz- noch Flächentoleranzen
werden erhöht; die originalen 24.937 Messergebnisse und die
beiden Quell-GeoPackages werden nicht verändert.

Statt eine dritte Reparatur auf Verdacht einzuführen, liefert
`scripts/diagnose_wien_export.py` eine **rein lesende, genau
auf diese GIP-ID begrenzte** Untersuchung der fertigen
Begrünungs-GeoPackage-Geometrien. Die Diagnose speichert in
einer ZIP-Datei vollständige originale EPSG:31256-WKB-Fragmente
und deren Union sowie WGS84 vor/nach make_valid, metrische
Rückprojektion vor/nach make_valid, Normal-Roundtrip und
zusätzliche bzw. fehlende metrische Flächen. Dazu kommen
kleine 3-m-Ausschnitte rund um die genannte Fehlerkoordinate
und ein JSON-Bericht mit Prüfergebnissen und Original-WKB-SHAs.

~~~bash
git pull --ff-only
.venv/bin/python -m unittest discover -s tests \
	-p 'test_diagnose_wien_export.py' -v
.venv/bin/python -m scripts.diagnose_wien_export \
	--gip-id 10023323 \
	--lon 16.2140370087171 \
	--lat 48.2445637429625 \
	--out data/processed/wienweit/wien/diagnose-export-wgs84.zip
~~~

Die ZIP muss für die Ursachenprüfung analysiert werden;
der Quellcode führt **keinen** Geometrieexport und keine
zusätzliche Fachklassifikation durch. Ein zweiter Aufruf mit
einem bereits vorhandenen ZIP-Pfad wird sicher abgewiesen.
Die vorhandenen Ausgaben bleiben unverändert.
## WGS84 GIP 10023323: Ursachenbefund aus Original-WKB und eng begrenzte Ausgabe-Normalisierung

Die vollständige, read-only erstellte Diagnose-ZIP für GIP
`10023323` wurde untersucht. Sie enthält **ein** originales
EPSG:31256-Fragment (FID 28649, MultiPolygon), aufgeteilt in
**vier** geometrische Teilpolygone. Gesamtfläche
**638,111419394619 m²**, Grenzlänge **231,373390 m**.

Das dritte Polygon (Teilpolygon-Index 2, nullbasiert)
ist ein tatsächlich im Original metrisch als gültig
eingestuftes, aber numerisch kollabiertes Dreieck mit:

- Fläche **2,333480630944962 × 10^-13 m²**;
- Polygonumfang **0,6130202683 m**;
- den praktisch identischen Punkten
  `(-8771.310688095295,345139.10842805094)` und
  `(-8771.310688095296,345139.10842805094)`.

Nach der unveränderten WGS84-Transformation hat dieses
Teilpolygon **exakt Fläche 0**, weil die beiden Punkte auf
dieselben WGS84-Koordinaten gerundet werden. `make_valid`
wandelt es in eine Linie, die beim rein polygonalen GeoJSON-
Export wegfällt. **Diese etwa 30 cm lange flächenlose Linie**
erklärt die gemessene Grenzabweichung **0,2964237907 m**,
obwohl der Flächenunterschied nur etwa **0,000002585 m²**
beträgt. Die übrigen drei Teilpolygone bleiben als
flächenhafte Geometrien erhalten.

**Entscheidung:** Keine Erhöhung der 1-cm-Grenztoleranz.
Stattdessen ist für den **Publikationsweg allein** die
streng begrenzte Funktion `_collapsed_wgs84_parts` ergänzt:

- Sie greift nur, wenn die vollständige WGS84-Ausgabe
  ohnehin ungültig ist und die metrischen und WGS84-
  MultiPolygon-Komponenten 1:1 korrespondieren.
- Ein Teilpolygon darf nur entfallen, wenn es metrisch
  **maximal 1 × 10^-9 m²** Fläche und **maximal 1 m**
  Umfang hat, in WGS84 ungültig ist, dort **exakt 0 Fläche**
  besitzt und sein `make_valid` **keine Polygonfläche**
  mehr enthält (also tatsächlich nur Linie/Punkt ist).
- Die Summe der entfallenen metrischen Teilflächen
  darf **1 × 10^-9 m²** nicht überschreiten. Zumindest
  ein gültiger polygonaler Teil muss erhalten bleiben.
- Nur die so gefilterte, gültige Publikationsgeometrie
  wird direkt nach WGS84 transformiert. Die WGS84-Ausgabe
  darf dadurch keine zusätzlichen ungültigen Flächen erhalten.
- Der unveränderte metrische Gesamtabschnitt bleibt in
  CSV/GPKG und allen Messwerten bestehen. Für die
  abschließende metrische Kontrollprojektion wird
  die explizit protokollierte, um die numerisch
  kollabierte Nullfläche bereinigte **Publikationsquelle**
  herangezogen. Für deren verbliebene Flächen gelten
  unverändert die Flächen-, Differenz- und
  1-cm-Grenzprüfungen.
- Der Prüfbericht dokumentiert jedes absichtlich
  nur im GeoJSON entfallene Teilpolygon mit Teilindex,
  Quellfläche, Umfang, Bounds und WGS84-Fehlergrund.
  Ebenfalls enthalten: Grenzabweichung gegen die
  verbliebene Publikationsquelle **und zusätzlich gegen
  den unveränderten metrischen Gesamtabschnitt**.

Ein lokaler Test mit den echten ZIP-WKBs ergab vor dem
Code-Commit für den um genau diese Kollapskomponente
bereinigten Abschnitt: WGS84 **gültig**, metrisch
zurückprojiziert (nach bereits vorhandenem kontrolliertem
make_valid) nur **0,001038 m** Grenzabweichung zur
gefilterten Publikationsquelle. Der alte Wert gegen
das unveränderte Original bleibt ca. 0,296424 m
und wird **nicht verschwiegen**.

Die Regressionen enthalten einen synthetischen
Nachbau dieses tatsächlich beobachteten Rundungsfalls,
Gegenbeispiele für nicht kollabierte und lange Teile
und einen optionalen Test mit dem echten ZIP:

~~~bash
git pull --ff-only
WIEN_EXPORT_DIAG_ZIP=data/processed/wienweit/wien/diagnose-export-wgs84.zip \
	.venv/bin/python -m unittest discover -s tests \
	-p 'test_wienwide_result_export.py' -v
bash scripts/run-wien-gartenstrassen.sh --from export --until export
~~~

Die Tests und der reale Export müssen noch lokal
bestätigt werden; die vorangegangene Diagnose ersetzt
keine erfolgreiche Wiederholung des gesamten Publikationslaufs.
## Wien-Export: erneuter GIP-Fall und gesamthafte WGS84-Vorprüfung (16.10.2026)

Nach der sehr engen und durch Original-WKB bestätigten Ausnahme
für GIP 10023323 hat der vollständige Export für
**GIP 10023775** erneut korrekt abgebrochen:

~~~text
Too few points in geometry component[16.3850399720429 48.301281942119]
Flächenänderung: +0.000002428 m², Grenze: 0.010000 m²
Zusätzlich: 0.116235004 m², fehlend: 0.116232576 m²
Je Differenzschranke: 0.821692 m²
Maximale Grenzabweichung: 6.070347 m, Schranke: 0.010 m
~~~

**Die Ursache dieses neuen Falls ist unbekannt**, solange die
Original-WKB von 10023775 nicht vorliegt. Ein flächenmäßig
kleiner, aber sechs Meter langer Ausläufer wäre eine andere
räumliche Situation als die 0,613-m-Komponente von 10023323.
Deshalb: keine Vergrößerung der 1-cm-Toleranz und der
automatischen Nullflächen-Ausnahme.

Um wiederholte abgebrochene Veröffentlichungsversuche zu
vermeiden, gibt es nun die unabhängige, **schreibgeschützte**
komplette WGS84-Exportvorprüfung `scripts/scan_wien_export.py`.

- Die Vorprüfung verwendet dieselbe 100-m²-GIP-ID-Filterung
  und dieselbe CSV/GPKG-Flächen- und Provenienzprüfung
  wie `wienwide_result_export.py`.
- Sie iteriert sämtliche ausgewählten GIP-IDs in einem
  Durchlauf, vereinigt Kachelfragmente in EPSG:31256,
  projiziert nach EPSG:4326 und ruft
  **dieselbe** Funktion `_verified_wgs84` auf.
- Anders als `export` protokolliert sie jeden GIP-Fehler
  und setzt mit der folgenden ID fort; Fehler werden
  **nicht** als erfolgreiche Publikation gewertet.
- Der JSON-Bericht zählt alle untersuchten, bestandenen
  und fehlgeschlagenen GIP-IDs und nennt **alle** fehlerhaften
  IDs mit genauer Fehlermeldung und Abschnittsfläche.
- Bis zu 25 betroffene IDs erhalten zusätzlich Original-WKB,
  Projektionen, make_valid-Zwischenstände, Differenzflächen
  und gegebenenfalls 10-m-Fehlerstellen-Ausschnitte in
  `wgs84_export_fehlstellen.zip`. Das Bericht-JSON weist
  explizit aus, falls mehr als 25 Fehler vorkommen.
- Quell-CSV und GeoPackage bleiben unangetastet;
  die Diagnose legt keine GeoJSON-Publikationsdatei an
  und ändert keine Grenzwerte. Vorhandene Diagnoseberichte
  werden nicht überschrieben.

**Zunächst nur die Vorprüfung starten, nicht den Export:**

~~~bash
git pull --ff-only
.venv/bin/python -m unittest discover -s tests \
	-p 'test_scan_wien_export.py' -v
.venv/bin/python -m scripts.scan_wien_export
~~~

Danach den vollständigen JSON-Bericht und die Diagnose-ZIP
der Fehlstellen analysieren. Insbesondere GIP 10023775 muss
vor einer weiteren Codeänderung anhand echter Geometrie
untersucht werden. Eine fachliche Freigabe von Polygonen
mit Grenzabweichungen über 1 cm wird aus dem Scan
**nicht** abgeleitet.
## WGS84-Vorprüfung komplett: 76 Fehler, Präzisionsnormalisierung der Veröffentlichung (16.10.2026)

Die vollständige schreibgeschützte Vorprüfung vor dem Wien-Export
ergab aus 24.937 Mess-GIP-IDs nach dem 100-m²-Filter
**24.306** Veröffentlichungs-IDs. **24.230** bestanden die
aktuelle Prüfung, **76** scheiterten und **150** gesonderte
WGS84-Korrekturereignisse waren bereits akzeptiert.
Fehlertypen unter den 76: **57** `Too few points`,
**12** `Ring Self-intersection` und **7** `Self-intersection`.
Die erste Diagnose-ZIP enthält die vollständigen Original-WKB
von **25** der 76 Fehler, 51 stehen nur im JSON-Bericht.

Bei allen 25 WKBs wurde die Originalgeometrie direkt untersucht.
Die Fälle sind nicht nur einzelne isolierte Mikro-Multipolygon-
Teile: teilweise gibt es extrem schmale Längsausläufer
innerhalb größerer gültiger metrischer Polygone. Einzelne
Spitzen besitzen fast keine Fläche und dennoch mehrere Meter
Länge; etwa GIP **10023775** mit zwei flächenlosen
Einzelteilen zu ca. **3,02 m und 12,14 m Umfang**.
Der bisherige mikro-Polygon-Filter mit 1 m Maximalumfang
genügt daher nicht.

**Getestete alternative Behandlung für die Publikation:**
Ein präziser fester metrischer Koordinatenraster von
**10 Nanometern (`1e-8 m`)**, mit
`shapely.set_precision(..., mode='valid_output')`.
Bei ALLEN 25 untersuchten echten Original-WKBs war danach
die WGS84-Transformation gültig. Ein lokaler unabhängiger
Geometrie-Test prüfte außerdem bei allen 25 die metrische
Rücktransformation, Fläche, fehlende/zusätzliche Fläche
und verbliebene Grenzverschiebung.
Die größte betragsmäßige Änderung der metrischen
Abschnittsgesamtfläche war rund **1,4 × 10^-7 m²**;
zusätzliche und fehlende Flächen waren jeweils
**unter 4 × 10^-7 m²**. Die Rückprojektion der
normalisierten WGS84-Geometrie wich von der normalisierten
metrischen Basis maximal etwa **1,1 mm** ab.

**Sicherer Fallback in `wienwide_result_export.py`:**

- Der bisherige `_verified_wgs84`-Weg bleibt **vorrangig**;
  bereits erfolgreich geprüfte WGS84-Ausgaben werden
  dadurch NICHT umgeschrieben.
- Nur nach dem konkreten Abbruch `Reparatur nicht metrisch
  flächentreu` wird zusätzlich die 10-nm-Normalisierung
  der **Publikationsquelle** versucht. Sie muss mit
  der unveränderten direkten WGS84-Transformation aus
  genau demselben originalen metrischen Polygon beginnen.
- Original-CSV, Original-GeoPackage, originale EPSG:31256-
  WKB und sämtliche Messwerte bleiben **unverändert**.
- Die metrische Normalisierung darf jeweils höchstens
  `max(1e-6 m², Ausgangs-Grenzlänge × 1e-7 m)` an
  fehlender oder zusätzlicher Fläche verursachen;
  auch der Nettoflächenunterschied muss darunter liegen.
  Das ist ein zusätzlicher Schutz, kein Grenzwert für
  die folgenden metrischen Projektionstests.
- Nur eine gültige und nicht leere polygonale
  normalisierte Metrik mit **gültiger WGS84-Transformation**
  darf verwendet werden. Danach gelten erneut die
  bisherige Gesamtflächen-, Differenzflächen- und
  **1-cm-Hausdorff-Grenze** gegen die bereinigte
  Publikationsquelle.
- Die Hausdorff-Abweichung zum **unbereinigten Original**
  wird separat und ungekürzt im Exportbericht protokolliert:
  denn eine praktisch flächenlose meterweit reichende
  Spitze kann durch den Raster kollabieren. Der Bericht
  dokumentiert ebenfalls Rastergröße, entfernte/hinzugefügte
  Fläche, Flächenbilanz und wiederholte Projektionstests.
- Scheitert eine dieser Bedingungen, bleibt der Export
  abgebrochen. Die Original-Fehlermeldung und der Grund
  für die abgelehnte Zusatznormalisierung werden
  gemeinsam ausgegeben.

**Wichtig:** Dass die normalisierte Geometrie fast
flächenidentisch ist, bedeutet NICHT, dass die
originale metrische Grenzlinie hausdorffgleich bleibt.
Der Unterschied wird nur für mathematisch innerhalb
eines 10-nm-Rasters zusammenfallende Strukturen
zugelassen und ausdrücklich als geometrischer
Publikationsartefakt ausgewiesen. Der unveränderte
metrische Messdatensatz ist die maßgebliche
fachliche Datenbasis.

**Noch keine automatische Freigabe** des kompletten
24.306-GIP-Wien-Exports: Von den 76 Fällen liegen nur
25 originale WKBs zur Prüfung vor. Nach den Tests
unbedingt erst die unabhängige Komplett-Vorprüfung
mit **neuen Berichtspfaden** wiederholen:

~~~bash
git pull --ff-only
WIEN_EXPORT_FEHLSTELLEN_ZIP=data/processed/wienweit/wien/wgs84_export_fehlstellen.zip \
	.venv/bin/python -m unittest discover -s tests \
	-p 'test_wienwide_result_export.py' -v
.venv/bin/python -m scripts.scan_wien_export \
	--report data/processed/wienweit/wien/wgs84_export_vorpruefung_praezision.json \
	--zip data/processed/wienweit/wien/wgs84_export_fehlstellen_praezision.zip
~~~

Auch wenn der Scan anschließend null Fehler meldet,
bleibt der eigentliche GeoJSON-Export ein separater
bewusst erst danach auszuführender Schritt.
## Vektor-PMTiles aus dem geprüften Wien-Export (16.10.2026)

Der finale Wien-Export nach vollständiger, fehlerfreier WGS84-
Vorprüfung ist abgeschlossen: 24.306 GIP-IDs mit jeweils
mindestens 100 m², aus insgesamt 24.937 GIP-IDs.
Die Geometriekontrolle protokollierte 226 WGS84-Ausgabekorrekturen,
die Metrik und Quell-GPKGs wurden nicht verändert.

Für eine performant abrufbare **Visualisierung in der Kartensammlung**
kann die vorhandene Publikations-GeoJSON direkt in
**PMTiles v3 mit Mapbox Vector Tiles (MVT)** überführt werden.
Dies geschieht als bewusster, **separater Build-Schritt**,
nicht als neue automatische Pflichtphase des rechenintensiven
Wien-Laufs.

**Werkzeug:** Felt/Tippecanoe **ab v2.17** unterstützt
PMTiles direkt. Die auf Ubuntu installierte `tippecanoe`-Version
mit `tippecanoe --version` prüfen; ältere Pakete können
nur MBTiles liefern. Gegebenenfalls die aktuelle
`felt/tippecanoe`-Version installieren. Für zusätzliche
Archivinhalts-/Strukturprüfung kann `pmtiles verify`
(Protomaps-Go-CLI) installiert werden.

~~~bash
git pull --ff-only
.venv/bin/python -m unittest discover -s tests \
	-p 'test_build_wien_pmtiles.py' -v
tippecanoe --version
# Optional: prüfen, ob der Protomaps-Verifizierer vorhanden ist:
command -v pmtiles || true
.venv/bin/python -m scripts.build_wien_pmtiles

# Vorhandene Zoom-12–17-Datei ohne Sicherung überschreiben:
# Minzoom 8, Maxzoom unverändert 17:
.venv/bin/python -m scripts.build_wien_pmtiles --replace
~~~

**Lokale Ausgaben (bestehender Exportordner):**

- `data/processed/wienweit/wien/veroeffentlichung_100m2/gartenstrassen_wien.pmtiles`
- `data/processed/wienweit/wien/veroeffentlichung_100m2/pmtiles_bericht.json`

**Eigenschaften:** Layer-Name `gartenstrassen_wien`, Zoom
**8 bis 17**, `full-detail` und `low-detail` jeweils 12
(4096 Tile-Units), maximale Zoomstufe ohne
Tippecanoe-Linienvereinfachung; die niedrigeren
Zoomstufen werden für die Darstellung vereinfacht.
Feature-IDs sind aus `gip_id` numerisch konvertiert;
das String-Attribut `gip_id` bleibt als Fach-ID erhalten.
Beide Begrünungsprozente, Flächenkennzahlen, Straßenname,
FOW und alle weiteren CSV-Attribute bleiben im MVT-Layer.
Kein Coalescing, keine dynamische Feature-Ausdünnung,
keine automatische Verkleinerung über Tile-Grenzwerte
und keine Repräsentation winziger Polygone als Rechtecke.

**Unabhängige Eingangs-QA:** Der Build gleicht die
vollständige gefilterte CSV mit dem GeoJSON in einem
speichersparenden Feature-Stream ab (vollständiger
ID-Satz, 24.306 Einträge, Felder und Zahlen, gültige
nichtleere Polygone). Er liest und überprüft den
vorhandenen Exportbericht; seine Quelldateien werden
nicht verändert. Das Eingangs-GeoJSON ist bereits
EPSG:4326 und wird nicht noch einmal projiziert.

**Sicherung des Archivs:** Tippecanoe schreibt
`gartenstrassen_wien.tmp.pmtiles`, das mindestens die
PMTiles-v3-Signatur und eine vollständige Headerlänge
aufweisen muss. Falls der Protomaps-Befehl `pmtiles`
im PATH liegt, wird `pmtiles verify` ausgeführt;
das Prüfprotokoll enthält ausdrücklich, ob diese
zusätzliche Archiv-Strukturprüfung verfügbar war.
Erst anschließend entstehen die endgültige `.pmtiles`-
Datei und ein Manifest mit SHA-256-Prüfsummen,
Quell-GIP-Anzahl, Zoomstufen und Werkzeugversion.
Vorhandene PMTiles-Ausgaben werden ohne ausdrückliches `--replace` nicht überschrieben.
Mit `--replace` wird das neue Archiv zunächst vollständig separat in
der temporären Datei erzeugt, geprüft und gehasht. Bis dahin bleibt
das vorhandene PMTiles unverändert. Nach erfolgreicher Prüfung werden
Manifest und PMTiles durch direkte Dateiumbenennungen ersetzt.
**Es werden keine Sicherungskopien, `.previous`-Dateien oder Versionen
der früheren PMTiles-Datei angelegt.** Die letzte Umbenennung ist
die des fertig geprüften PMTiles-Archivs. Falls diese fehlschlägt,
wird der vorherige kleine JSON-Bericht aus dem Arbeitsspeicher
wiederhergestellt; die ursprüngliche PMTiles-Datei bleibt erhalten.
Die beiden Umbenennungen sind jeweils atomar, aber nicht als
gemeinsamer Transaktionsschritt atomar.

**Wichtige fachliche Grenzen:**

- Die Kartensammlung verwendet die Tiles als **Anzeigedaten**,
  NICHT zur metrisch präzisen Flächenmessung: MVT
  quantisiert WGS84-/Web-Mercator-Koordinaten nach
  Zoomstufe und schneidet Features an Kachelgrenzen.
- Niedrige Zoomstufen können kleine/schmale Abschnitte
  wegen begrenzter Rasterauflösung nicht darstellen.
  Aus 24.306 vollständigen GeoJSON-Features folgt
  nicht 24.306 MVT-Features pro Zoomstufe oder Kachel.
- Die vollständige metrische Flächenbasis in EPSG:31256,
  die 100-m²-Export-CSV und das EPSG:4326-GeoJSON
  bleiben maßgeblich für Werte, Genauigkeit und QA.
- Prozentwerte werden **aus der CSV als Featureattribute**
  übernommen, nicht erneut aus vereinfachter
  MVT-Geometrie ermittelt.
- Die spätere Hosting-Umgebung braucht HTTP-Range-Requests
  und bei Cross-Origin-Zugriff korrektes CORS.
  Quellennennung/Attribution vor der externen
  Veröffentlichung fachlich klären, nicht erfinden.

Der erste lokale PMTiles-Build wurde am 16.10.2026 mit
Tippecanoe 2.49.0 erfolgreich erstellt: 24.306 Quell-Features,
Zoom 12–17, 31.180.788 Bytes. Für den Debug-Einsatz
wurde anschließend der Build auf **Zoom 8–17** umgestellt;
der lokale Neubau mit direktem Überschreiben und ohne Sicherung
erfolgt mit `--replace`.
Die erzeugten Geodaten liegen absichtlich nicht im Git-Repository. Die Kartenintegration
erfolgt erst nach Sichtprüfung von Dateigröße,
Tile-Grenzen, Hover-Kennung, Attributen und Ladezeiten.
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
