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
