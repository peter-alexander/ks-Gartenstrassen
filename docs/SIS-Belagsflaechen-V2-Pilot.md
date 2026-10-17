## Wienweiter SIS-Lauf mit externem Datenspeicher

Die große Wien-Variante verwendet konsequent `/mnt/e/Gartenstrassen/`
(WSL-Mount einer externen/zweiten Windows-Partition). Rohdaten, zentrale
SQLite und alle großen Analysezwischenstände werden **nicht** im Repository
und nicht auf der primären SSD abgelegt.

- `/mnt/e/Gartenstrassen/wfs-kacheln/`: originale WFS-Antworten als
  `.geojson.xz` (LZMA2, Preset 6), mit Metadaten und Prüfsummen
- `/mnt/e/Gartenstrassen/sis-wien.sqlite`: eindeutige SIS-Features
  (OBJECTID oder WFS-ID), vollständige metrische Geometrien, R-Tree
  und transaktionssicheres Importprotokoll
- `/mnt/e/Gartenstrassen/aoi/wien.geojson`: amtliche Wien-Grenze
- `/mnt/e/Gartenstrassen/analysis/wien/`: GIP-Index, Straßenraum,
  Rohpartition, gekürzte Voronoi-Partition, QA und Ergebnisdateien

Die WFS-Requests umfassen 1.900 × 1.900 m (1.700-m-Kern plus jeweils
100 m Überlappung). Die Originalfeatures werden **nicht** an WFS-
Requestgrenzen abgeschnitten. Der Import schreibt ausschließlich fehlende
Features, prüft widersprüchliche Dubletten und commitet jede Kachel atomar.
Nach erfolgreichem Import aller Kacheln erfolgt der Rechenlauf aus dem
zentralen räumlichen Index. Der vorhandene Testausschnitt-Lauf bleibt erhalten.

Ausführung unter WSL mit vorhandenem `/mnt/e`, Python-Venv und lokaler
GIP2-Quelle:

```bash
bash scripts/run-sis-v2-wien.sh
```

Das Skript lädt fehlende Kacheln nach und setzt bei vorhandenen Imports fort.
Es löscht den Rohcache nicht. **Der vollständige Wien-Lauf ist noch nicht
mit den echten Gesamtdaten validiert**; insbesondere müssen Ressourcenbedarf
und Voronoi-Grenzen im Gesamtbestand geprüft werden.

# SIS-Belagsflächen – V2-Pilot (17.10.2026)

## Eingabe

Der erste Test verwendet **exakt** die bereits vorhandene Testdatei:

`https://tiles.radlobby.at/Gehsteigbreiten/Testdaten/SISBELAGOGD.json`

Sie ist nur ein Ausschnitt und ausdrücklich **kein vollständiger Wien-Datensatz**.
Die Testdatei kann automatisch einmal geladen oder unter `--source-file`
lokal übergeben werden. Es erfolgen keine neuen WFS-Anfragen für diesen Test.
Es werden **alle** `TYPE`-Klassen übernommen; die für Gehsteigbreiten
verwendete Filterung auf GG/EE/HH wird hier **nicht** angewandt.

## Ausführen

~~~bash
# Python-Umgebung laut README vorbereiten.
.venv/bin/python -m scripts.sis_belagsflaechen

# Alternativ, falls die Datei bereits lokal vorliegt:
.venv/bin/python -m scripts.sis_belagsflaechen \
	--source-file /pfad/SISBELAGOGD.json \
	--out-dir data/processed/sis-pilot-v2

# Offline-Tests:
.venv/bin/python -m unittest tests.test_sis_belagsflaechen -v
~~~

## Ausgabe und Sicherheitsregeln

- `SISBELAGOGD.json`: unveränderte Kopie der Eingabe.
- `sis.sqlite`: alle Einzelpolygone in EPSG:31256, Klasse `TYPE`,
  RTree-Index für Teilflächenabfragen, dazu `street` als geometrische
  Vereinigung aller Belagsflächen **ohne** Kreuzungsabzug.
- `bericht.json`: SHA-256, Featurezahl, Klassenhäufigkeiten,
  Summen-/Vereinigungsflächen, Überlappungsdifferenz.
- Bestehende Ergebnisordner werden nicht überschrieben.
- Ungültige Polygone, fehlendes `TYPE`, unpassende Koordinaten oder
  ein widersprüchliches CRS führen grundsätzlich zum Abbruch. Eine Ausnahme
  ist nur für nachweislich flächenlose degenerierte Ringe vorgesehen:
  `make_valid` darf ausschließlich polygonale Bestandteile übernehmen und
  muss sowohl Flächendifferenz als auch symmetrische Differenz innerhalb der
  protokollierten metrischen Toleranz halten. Jede solche Korrektur steht mit
  Quell-ID, SIS-ID und Flächenbilanz in `sis/bericht.json`.

## Durchgängige SIS-V2-Pipeline

Die gesamte V2-Auswertung ist jetzt über einen eigenständigen Treiber
erreichbar; keine FMZK-/BEV-Katastereingaben nötig:

~~~bash
bash scripts/run-sis-v2-pilot.sh
~~~

Der vollständige Pilot verwendet standardmäßig die bereits lokal vorhandene
`data/raw/SISBELAGOGD.json` sowie `data/raw/gip_network_ogd.gpkg`. Die Dateien
werden nicht erneut heruntergeladen.
Falls der Pfad auf einem anderen System abweicht, kann `SIS_V2_SOURCE`
gesetzt werden.

Optional eine bereits vorhandene Testdatei übergeben:

~~~bash
SIS_V2_SOURCE=/pfad/SISBELAGOGD.json bash scripts/run-sis-v2-pilot.sh
~~~

Der neue Pilot bleibt vollständig getrennt von V0 unter
`data/processed/sis-v2-run/`. Das Pilot-AOI wird aus dem metrischen
Umgrenzungsrechteck der SIS-Testdatei erzeugt, mit 250-m-Arbeitskacheln
und 75-m-Halo. Die GIP-Geometrien werden aus dem lokalen GIP-2.0-GeoPackage
gelesen; die GRM2023-Baumschicht wird über das bestehende, quellengeprüfte
Abrufmodul für dieses Gebiet bezogen.
`--from` und `--until` erlauben einzelne Phasen. Mit `--no-grm`
kann die Kronenberechnung zunächst ausgelassen werden; in diesem Fall
bleiben Kronenwerte im Ergebnis `null`.

V2-Ausgaben:

- `qa.gpkg`: vollständige GIP-Voronoi-Partition nach Abzug der aus TURN_USE
  gebildeten konvexen Kreuzungshüllen, mit Kreuzungs- und Restflächen als
  geometrischer QA.
- `ergebnisse/gip_abschnitte.csv` und `.geojson`: GIP-Abschnitte,
  SIS-Bodenkennzahlen sowie optional GRM2023-Überschirmung.
- `ergebnisse/bericht.json`: Herkunft und Bilanz sowie
  die tatsächlich verwendeten Klassifikationsregeln.
- `gartenstrassen_sis_v2.pmtiles`: separate Publikationskacheln,
  GIP-Abschnitte ab 100 m², Zoom 8 bis 17; benötigt `tippecanoe`.

Die Flächen werden binär klassifiziert: **BELAG BL, ST oder WI = Bodenbegrünung**;
alle übrigen BELAG-Codes = nicht begrünt. Sämtliche TYPE-Klassen,
einschließlich Mauern (M1/M2), gehören zur gesamten SIS-Fläche.
Ausgabefelder: `boden_m2`, `boden_pct`, `nicht_begruent_m2`,
`nicht_begruent_pct`. Der Nenner ist die komplette SIS-Voronoi-Abschnittsfläche.
Dieselbe Gesamtfläche ist auch der Nenner der GRM2023-Baumkronenquote;
deren Zähler ist ausschließlich die GRM2023-Kronenfläche im Abschnitt.
Bodenbegrünungs- und Überschirmungsprozente werden nicht addiert.

**Qualitätssicherung:** Quellüberlagerungen werden mit den IDs beider
SIS-Features und ihrer Schnittfläche in `sis/bericht.json` protokolliert.
Überlagerungen derselben binären Bodenklasse werden vereinigt und dadurch
nicht doppelt gezählt. Überschneiden sich begrünte und nicht begrünte
Beläge nur als numerische Randsplitter bis 0,01 m², gilt konservativ
„nicht begrünt“; ein größerer Klassifikationskonflikt bricht den Lauf ab.

Die aktuelle GIP-2.0-Zuordnung verwendet Voronoi-Flächen nach Abzug
datengetriebener konvexer TURN_USE-Kreuzungshüllen. Sie verwendet keine
pauschalen 7-m-Kreuzungskreise. V0 bleibt unverändert.

## Historischer erster SIS-Testlauf vom 17.10.2026

Der vollständige Lauf mit `data/raw/SISBELAGOGD.json` ist einschließlich
GIP-Abruf und -Voronoi, GRM2023, QA und PMTiles erfolgreich abgeschlossen.
Die unveränderte Eingabe und ihre Kopie haben beide SHA-256
`17f89e01ea7ac8c27390ba76ffa889a34d1b52b10ac67e4cbcfbcfd8041a8a36`.

| Größe | Ergebnis |
| --- | ---: |
| SIS-Features, alle TYPE-Klassen einschließlich M1/M2 | 28.122 |
| Brutto-Summenfläche vor Vereinigung | 1.079.955,147 m² |
| Vereinigter SIS-Straßenraum | 1.079.759,478 m² |
| Dokumentierte Quellüberlagerung | 195,670 m² |
| Widersprüchliche Bodenklassen-Randsplitter | 0,002757 m² |
| Reguläre, geometrisch eindeutige GIP-IDs | 736 |
| GIP-Abschnittsteile im QA-GeoPackage | 1.126 |
| Regulär zugeordnete Abschnittsfläche | 927.885,165 m² |
| Sonderachsen | 133.996,946 m² |
| Sonstige nicht zugeordnete Fläche | 17.877,367 m² |
| Gesamte nicht regulär zugeordnete Fläche | 151.874,312 m² / 14,0656 % |
| Flächenbilanzdifferenz | −0,000000001 m² |
| Bodenbegrünung in regulären Abschnitten | 32.199,576 m² / 3,4702 % |
| GRM2023-Kronenfläche in regulären Abschnitten | 65.597,842 m² / 7,0696 % |

Eine Geometrie wurde korrigiert: Feature 6266,
`SISBELAGOGD.1135624723`, SIS-ID 3584640, enthielt einen degenerierten
Innenring mit nur zwei verschiedenen Punkten. `make_valid` ergab eine
GeometryCollection; übernommen wurde ausschließlich das Polygon, die
flächenlose LineString-Komponente wurde verworfen. Die Fläche änderte sich
von 30,610802784743 m² auf 30,610802784743 m²
(Delta 0,000000000000007 m²; symmetrische Differenz 0 m²).

Die vollständigen 736 Abschnittsergebnisse stehen in CSV und GeoJSON.
Für PMTiles gilt wie bei V0 ausschließlich als Darstellungsfilter die
Mindestfläche 100 m²: 710 GIP-IDs sind enthalten, 26 kleinere IDs mit
zusammen 795,877 m² bleiben nur in den vollständigen Ergebnisdateien.
Die Referenzwerte bleiben 40 % Bodenbegrünung und 60 % Überschirmung.


## Aktueller Versuch: Voronoi-Straßenarme automatisch kürzen

Zunächst wird die vollständige SIS-Fläche ohne TURN_USE-Ausschnitte und ohne
7-m-Kreise auf **alle** lokalen GIP2-EDGE-Achsen nach Voronoi verteilt.
Diese unveränderte Partition liegt in `aufteilung_roh.sqlite`.

Der nachgeschaltete Schritt `trim` untersucht die zugehörige Voronoi-Fläche
entlang jeder EDGE von `node_from` und `node_to` aus. In 1-m-Abständen
werden senkrechte Querschnitte gemessen; maßgeblich ist nur der Linienanteil,
der die jeweilige EDGE-Achse schneidet. Die erste Folge von fünf Querschnitten
mit einer Spannweite von höchstens 10 % der Medianbreite wird verwendet,
wenn davor eine um mindestens 20 % kleinere Breite beobachtet wurde.
Die Suche endet spätestens bei 40 m bzw. vor der Mitte der EDGE.

An dieser Stelle wird die Voronoi-Fläche tatsächlich geteilt: Der verbleibende
Straßenabschnitt behält seine GIP-ID, der entfernte Teil wird als
`knotenbereich` geführt. Die fertige `aufteilung.sqlite` sowie
`qa.gpkg`, Kennzahlen und PMTiles verwenden die gekürzten Straßenabschnitte.
Die ausgeschnittenen Knotenbereiche bleiben im QA-Layer `knotenbereiche`
und in der Gesamtflächenbilanz. Falls kein stabiler Abschnitt erkannt wird,
wird die betreffende Seite **nicht** abgeschnitten. MultiLineString-EDGE
werden im ersten Versuch übersprungen.

Dies ist ein experimentelles geometrisches Verfahren, noch keine fachlich
validierte Kreuzungsabgrenzung. Der vollständige Standardlauf lautet:
`bash scripts/run-sis-v2-pilot.sh` und überschreibt nur den bekannten
V2-Ergebnisordner.

## GIP 2.0 / TURN_USE-Kreuzungshüllen (historischer Versuch)

Die aktuelle Pipeline verwendet **keinen Wiener GIP-WFS** mehr.
Zusätzlich zur lokalen SIS-Datei wird `data/raw/gip_network_ogd.gpkg` benötigt.

- `EDGE`: alle FOW-Klassen als Voronoi-Achsen, 5-m-Sites in EPSG:31256.
- `NODE`: Knotenmittelpunkte innerhalb der SIS-Bounding-Box.
- `TURN_USE`: alle Linien mit `via_node_id = NODE.object_id`.
- Pro NODE: konvexe Hülle aus sämtlichen zugehörigen TURN_USE-Linien unabhängig von `base_type`. Nichtpolygonale
  Hüllen werden protokolliert, nicht künstlich aufgeweitet.
- Alle Hüllen werden räumlich vereinigt und mit SIS geschnitten;
  nur der verbleibende Straßenraum wird den EDGE-Voronoi-Achsen zugeteilt.
- Die Kreuzungsflächen bleiben als `knotenbereiche` in `qa.gpkg` sichtbar.
  `junction_audit` und `junctions` in `gip.sqlite` enthalten
  Anzahl und Geometrie der konstruierten Hüllen.
- Verbindungsidentifikatoren sind GIP-2.0-UUIDs; ein Abgleich mit
  numerischen Wiener GIP_OBJECTIDs ist nicht erforderlich.
- SIS-Bodenbegrünung und GRM2023-Überschirmung bleiben unverändert definiert.

**Achtung:** Der Parser erwartet GeoPackage-Spatial-Indizes
`rtree_EDGE_geom`, `rtree_NODE_geom` und `rtree_TURN_USE_geom`.
Der neue Lauf überschreibt beim Start den bekannten V2-Arbeitsordner,
nicht die `data/raw`-Quelldateien. Er wurde gegen die lokale GIP-2.0-Datei
vollständig bis zum PMTiles durchgetestet.

Der reproduzierte vollständige Folgelauf vom 17.10.2026 ergab:

| Größe | Ergebnis |
| --- | ---: |
| Lokale GIP2-Achsen / 5-m-Voronoi-Sites | 3.014 / 37.920 |
| NODEs / polygonale TURN_USE-Hüllen | 1.808 / 1.506 |
| Geometrisch eindeutige GIP-IDs | 1.748 |
| GIP-Abschnittsteile im QA-GeoPackage | 2.382 |
| Regulär zugeordnete Abschnittsfläche | 945.188,627 m² |
| TURN_USE-Kreuzungsflächen | 133.714,033 m² |
| Sonstige nicht zugeordnete Fläche | 856,818 m² |
| Gesamte nicht regulär zugeordnete Fläche | 134.570,851 m² / 12,4630 % |
| Flächenbilanzdifferenz | +0,000000119 m² |
| Bodenbegrünung in regulären Abschnitten | 41.662,177 m² / 4,4078 % |
| GRM2023-Kronenfläche in regulären Abschnitten | 73.123,360 m² / 7,7364 % |

CSV und GeoJSON enthalten alle 1.748 IDs. Der PMTiles-Darstellungsfilter
ab 100 m² enthält 1.060 IDs; 688 kleinere Abschnitte mit zusammen
22.955,998 m² bleiben in CSV und GeoJSON erhalten.

~~~bash
git pull --ff-only
.venv/bin/python -m unittest tests.test_sis_gip2 -v
bash scripts/run-sis-v2-pilot.sh
~~~

## Noch offen / nächster Validierungsschritt



1. Die Testdatei später durch einen **gekachelten amtlichen WFS-Abruf**
   von `ogdwien:SISBELAGOGD` ersetzen. IDs, Dubletten,
   Abfragegrenzen und Vollständigkeit prüfen.
2. Die im aktuellen Folgelauf nicht den Abschnitten zugerechneten Flächen
   fachlich prüfen; sie bestehen überwiegend aus den konstruierten
   TURN_USE-Kreuzungshüllen und zu einem kleineren Teil aus sonstigen
   Restflächen.
3. Die TURN_USE-Kreuzungshüllen vor einer fachlichen Freigabe visuell prüfen;
   nichtpolygonale Hüllen bleiben im Audit sichtbar und werden nicht künstlich
   aufgeweitet.
4. Die technische QA ist abgeschlossen; vor einer fachlichen Freigabe für
   die Kartensammlung bleiben eine visuelle GIS-Prüfung und die Prüfung der
   GIP-/GRM-Abdeckung erforderlich.
