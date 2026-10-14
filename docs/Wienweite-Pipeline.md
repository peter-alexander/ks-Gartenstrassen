# Wienweite Pipeline: vorbereitete Phasen 1 und 2

**Stand 14.10.2026:** Technische Infrastruktur implementiert und synthetisch getestet. **Noch kein echter Bezirks- oder Wien-Gesamtlauf** mit vollständigen regionalen Daten. Der erfolgreiche kleine Modul-6-Test und seine V0-Daten bleiben unverändert.

## Gleichbleibende Methodik

Die vorläufige Modul-2-Straßenraumabgrenzung verwendet weiterhin FMZK-Kern 21/23/24/33/39 und bei anderen Flächen die BEV-Kataster-nfl-Klassen 95/65 mit mindestens 95 % Deckung. Unklare Objekte werden konservativ nicht zugeordnet.

GIP-V0 verwendet **5 m Abtastung, 7 m Knotenradius bei Grad >= 3, 25 m maximalen Achsabstand, FOW=3 für reguläre Abschnitte**. Kreuzungen und Sonderachsen bleiben getrennt. V1-Eckpunkt-Erkennung wird nicht weiterentwickelt.

## Neue Programme

| Programm | Aufgabe |
| --- | --- |
| scripts/wienwide_aoi.py | Wiener Bezirks-/Landesflächen als echte AOI-Polygone aus MA41-WFS abfragen |
| scripts/wienwide_grid.py | Festes Raster in EPSG:31256, AOI-/Manifest-Hash, Kachelkontrolle |
| scripts/wienwide_gip.py | WFS-Abrufe kachelweise mit Halo, Quelldaten-Cache, globale GIP-ID-Deduplizierung, SQLite-Graph und RTree-Index |
| scripts/wienwide_kataster.py | Bereits gespeicherte BEV-z16-MVT-Kacheln direkt in EPSG:31256 auswerten; nfl-Flächen ohne WGS84-GeoJSON-Rückweg |
| scripts/wienwide_street.py | Bestehende FMZK-/Kataster-Regeln auf lokale Quellkacheln anwenden und Ergebnis direkt als metrisches WKB/SQLite speichern |
| scripts/wienwide_partition.py | Voronoi-V0 anhand globaler 5-m-Stützpunkte kachelweise rechnen, Flächenbilanz und Ergebnis-Fragmente nach GIP-ID in SQLite speichern |
| scripts/wienwide_benchmark.py | Quellabdeckung, Kachel-Laufzeiten, partielle/vollständige Resultate und Flächenbilanz als JSON |

Der Halo beträgt zunächst **75 m**, die Kernkachel **1000 × 1000 m**. Es sind Benchmarkparameter, keine endgültigen Werte. Die Kachelgrenzen dienen ausschließlich der Berechnung; globale Site-IDs und Knotengrade stehen vor der Aufteilung fest. Kein GeoJSON-Rundweg für die maßgeblichen metrischen Flächen.

## Voraussetzungen

1. Bereits vorhandene vollständige FMZK-Originaldatei FMZK_WIEN_GP.gpkg (EPSG:31256).
2. **Echte** AOI-Polygone als GeoJSON/WGS84: Der neue Adapter ruft die offizielle Wiener WFS-Schicht BEZIRKSGRENZEOGD ab und kontrolliert alle 23 Bezirksnummern. Für den Pilot Alsergrund (9.) und Donaustadt (22.), optional die vollständige Wiener Landesfläche. Keine manuell erfundenen Bezirks-Bounding-Boxes.
3. GIP-WFS der Stadt Wien und BEV-Kataster-z16 dürfen abrufbar sein; Cache-Daten werden wiederverwendet.
4. Lokaler Datenträger für rasterweise FMZK, Kataster, GIP und SQLite. Keine belastbare Speicher-/Laufzeitschätzung vor Realtest.

## Beispiel: Bezirk Alsergrund

Die Pfade sind Beispiele und setzen eine echte lokale Bezirks-AOI voraus.

### 0. Verifizierte Bezirksflächen aus Wiener Open Data

~~~bash
.venv/bin/python -m scripts.wienwide_aoi   --bezirke 9 22 --wien   --out-dir data/raw/bezirke
~~~

Die AOIs entstehen als bezirk_09.geojson, bezirk_22.geojson
und optional wien.geojson. Die vollständige Rohantwort und
deren SHA-256 bleiben zur Reproduktion erhalten.
Quelle: Stadt Wien / MA41, BEZIRKSGRENZEOGD,
https://www.data.gv.at/katalog/dataset/2ee6b8bf-6292-413c-bb8b-bd22dbb2ad4b
(CC BY 4.0). Der WFS-Abruf selbst wurde noch nicht
in einem echten Bezirkslauf ausgeführt. Ein bereits
vorhandener Cache kann mittels --source als Eingabe
dienen. Bestehende AOIs werden nicht überschrieben.

### 1. Raster erstellen

~~~bash
git pull --ff-only
.venv/bin/python -m scripts.wienwide_grid \
  --aoi data/raw/bezirke/bezirk_09.geojson \
  --tile-m 1000 --halo-m 75 \
  --out data/processed/wienweit/alsergrund/raster.json
~~~

Das Raster ist fix in EPSG:31256 und vollständig auf die echte AOI beschnitten. Bei großen/fehlerhaften Kataster-Kacheln einen separaten **500-m-Plan** erstellen, nicht heimlich nur die Hälfte der Fläche auswerten.

### 2. GIP-Quellprobe, vollständiger Abruf und Index

~~~bash
.venv/bin/python -m scripts.wienwide_gip fetch \
  --manifest data/processed/wienweit/alsergrund/raster.json \
  --out-dir data/processed/wienweit/alsergrund/gip_fragmente \
  --limit-tiles 1

.venv/bin/python -m scripts.wienwide_gip fetch \
  --manifest data/processed/wienweit/alsergrund/raster.json \
  --out-dir data/processed/wienweit/alsergrund/gip_fragmente

.venv/bin/python -m scripts.wienwide_gip index \
  --manifest data/processed/wienweit/alsergrund/raster.json \
  --fragments data/processed/wienweit/alsergrund/gip_fragmente \
  --out data/processed/wienweit/alsergrund/gip.sqlite
~~~

Der Index lässt sich **nicht** aus unvollständigen Fragmenten erstellen. Leere WFS-Kacheln sind nach expliziter Prüfung erlaubt; Limitüberschreitungen, Duplikatkonflikte, falsches CRS oder fehlende GIP-Knoten am AOI-Rand führen zum Abbruch. Die Quelle und der Index bleiben unverändert.

**GIP-WFS-BBOX-Prüfung, aktualisiert 14.10.2026:** Beim
realen Alsergrund-GIP-Abruf wurden neun Kacheln erfolgreich
zwischengespeichert. Die achte hatte GIP_OBJECTID
`20028505`, dessen vollständige Linie **0,059 m** außerhalb
der WFS-Anfrage-BBOX lag; die zehnte meldete GIP_OBJECTID
`10023340` mit **1,309 m** Außenabstand. In beiden Fällen
schneidet auch das Geometrie-Hüllrechteck nicht die Anfrage.
Die exakte serverseitige Ursache ist **nicht** nachgewiesen.
Eine schrittweise größer werdende numerische Toleranz
wäre daher keine belastbare Lösung.

**Verbindliches Verhalten für neue Wien-Kacheln:**
Die WFS-BBOX wird als Kandidatenabfrage behandelt.
`validate_layer(..., filter_wfs_bbox_superset=True)` kontrolliert
**vor der lokalen räumlichen Filterung** die vollständige
WFS-Antwort, einschließlich GeoJSON/CRS, Featurelimit,
gemeldeter Gesamtzahl und sämtlicher vorhandener Geometrien.
Anschließend werden in die GIP-Arbeitsansicht ausschließlich
Geometrien übernommen, die die **bereits um 75 m
erweiterte Anfrage-BBOX tatsächlich schneiden**.
Außerhalb liegende Server-Kandidaten werden **nicht** in den
neuen GIP-Index aufgenommen, aber im Kachelbericht
unter `wfs_bbox_ausgeschlossen.<achsen|knoten>` mit Anzahl,
GIP-ID, `abstand_epsg3857_m` und Hüllrechteckstatus
dokumentiert. `wfs_antwort_features` enthält die Anzahl
**vor**, `anzahl` die Anzahl **nach** der Filterung.
Die Quellgeometrien werden nicht gepuffert, bewegt
oder gekürzt. Eine zu geringe Rückgabezahl/Featurelimit/
ungültige Geometrie bleibt weiterhin ein Fehler.

**Warum das methodisch zulässig ist:** Die GIP-Anfrage enthält
bereits einen **75-m-Halo** um den 1-km-Kachelkern,
V0 berücksichtigt für die Zuweisung dagegen
höchstens **25 m Achsabstand** und **7 m Knotenradius**.
Ein vollständiges Linien- oder Punktobjekt, das sogar
die vergrößerte Anfrage-BBOX nicht schneidet, kann
keinen Kernpunkt innerhalb dieser V0-Grenzen zuweisen.
Die zentrale, kachelübergreifende GIP-Deduplizierung
erfolgt weiterhin nach echten GIP-IDs; bisherige
gültige Kachel-Caches werden unverändert benutzt.
Zuvor in Kachel 8 gespeicherte Randkandidaten bleiben
deshalb weiterhin im alten Cache, müssen aber
**nicht gelöscht oder neu heruntergeladen** werden.

Der ursprüngliche streng prüfende GIP-Testgebiet-Adapter
bleibt unverändert im Default-Modus. Eine erfolgreiche
**lokale Ausführung über alle zehn Alsergrund-Kacheln**
und die Graphvollständigkeitsprüfung stehen nach
dieser Korrektur noch aus.

### 3. FMZK und Kataster

Zunächst die tatsächliche erste Tile-ID aus raster.json auswählen (der Platzhalter ist kein ausführbarer Name).

~~~bash
.venv/bin/python -m scripts.wienwide_street fetch-inputs \
  --manifest data/processed/wienweit/alsergrund/raster.json \
  --input-root data/processed/wienweit/alsergrund/eingaben \
  --fmzk-source data/raw/FMZK_WIEN_GP.gpkg \
  --kataster-cache data/cache/kataster \
  --only 'TILE-ID-AUS-MANIFEST'
~~~

Ist diese Probe korrekt, den Aufruf **ohne --only** wiederholen. Das Kataster-Skript verwendet dieselbe z16- und nfl-Auswertung wie das Testgebiet. Vorhandene BEV-Tiles werden gecacht; es werden keine unbekannten Nutzungen stillschweigend als Straße gerechnet.

~~~bash
.venv/bin/python -m scripts.wienwide_street build \
  --manifest data/processed/wienweit/alsergrund/raster.json \
  --input-root data/processed/wienweit/alsergrund/eingaben \
  --out-root data/processed/wienweit/alsergrund/strassenraum \
  --kataster-cache data/cache/kataster
~~~

Die resultierende street.sqlite liegt **je Tile** mit metrischer WKB-Geometrie und FMZK-/Kataster-Prüfsummen vor. Eine tatsächlich straßenraumfreie Kachel wird nach vollständiger Quellenauswertung explizit als leer markiert; fehlende Quelldaten sind dagegen ein Fehler.

**Fortsetzen nach erfolgreicher erster Alsergrund-Kachel (14.10.2026):**
Die Kachel `x+000001_y+000342` ergab **178.176,7 m²**
Straßenraum in **20,76 s**. `wienwide_street build` ist
ab jetzt wiederaufnehmbar: Existiert eine `street.sqlite`,
werden zuerst **Schema, Tile-ID, CRS, AOI-Fläche, Halo,
Fläche der WKB-Geometrie sowie Prüfsummen von FMZK,
Katasterbericht und allen BEV-z16-Rohkacheln** kontrolliert.
Erst dann wird die fertige Kachel übersprungen. Bei
irgendeiner Abweichung wird **abgebrochen**, nie überschrieben
oder still neu gerechnet.

Zum Fertigstellen von Alsergrund nach dieser ersten Kachel:

~~~bash
git pull --ff-only
.venv/bin/python -m scripts.wienwide_street fetch-inputs \
  --manifest data/processed/wienweit/alsergrund/raster.json \
  --input-root data/processed/wienweit/alsergrund/eingaben \
  --fmzk-source data/raw/FMZK_WIEN_GP.gpkg \
  --kataster-cache data/cache/kataster \
  --max-parcels 1500

.venv/bin/python -m scripts.wienwide_street build \
  --manifest data/processed/wienweit/alsergrund/raster.json \
  --input-root data/processed/wienweit/alsergrund/eingaben \
  --out-root data/processed/wienweit/alsergrund/strassenraum \
  --kataster-cache data/cache/kataster
~~~

`--max-parcels 1500` ist ein bewusst anpassbarer,
**technischer Schutzwert**, keine neue fachliche Regel.
`fetch-inputs` verwendet im Standardmodus **keine neuen
BEV-Grundstücks-Detailabfragen**. Falls eine weitere Kachel
den Schutzwert oder das Vektorkachellimit überschreitet,
Fehler prüfen und den Wert begründet anpassen, nicht die
Bezirksgrenze verkleinern.


**Realer Alsergrund-Pilot, nfl-Geometriefehler (14.10.2026):**
Bei der ersten Kachel `x+000001_y+000342` wurden **14.764 FMZK-Objekte** extrahiert, **36 BEV-z16-Kacheln** erfolgreich geladen und **811 Grundstücke** des FMZK-Straßenkerns ermittelt. Die 811 Klasse-D-Einträge bedeuten, dass die optionalen Grundstücksdetails nicht abgefragt wurden; die BEV-nfl-Vektorkacheln enthalten trotzdem die für die Straßenraumklassifikation benötigten Nutzungspolygone.

Der erste `wienwide_street build` brach bei `Keine gültige Polygonfläche: nfl #159` ab. Die damalige Funktion las `kataster_nfl_ausschnitt.geojson` und projizierte die ursprünglich metrisch erzeugten Fragmente **über WGS84 wieder zurück nach EPSG:31256**. Die Wien-weite Stufe verwendet deshalb jetzt `wienwide_kataster.py`: Es liest die **bereits lokal zwischengespeicherten BEV-Rohkacheln** ausschließlich offline, gleicht z16-Kachel-Liste, BBOX und die Anzahl der vom FMZK-Kern getroffenen Grundstücke mit dem vorhandenen Katasterbericht ab, beschleunigt das Polygon-Clipping mit einem räumlichen Index und verwendet die ursprünglichen metrischen nfl-Fragmente. Kein erneuter Download und keine neuen Grundstücks-Detailabfragen.

Nur wie bisher Quell-Schnittfragmente mit **höchstens 0,05 m²** werden ausgeschlossen und quantitativ berichtet; echte ungültige oder irreparabel flächenverlustige Polygonfragmente oberhalb dieser Schwelle führen weiter zum Fehler. Die 95-%-Regel und die Kategorien 95/65 bleiben unverändert. Der bestehende **kleine Testgebiets-Workflow ist unverändert**. Der metrische Rechenweg ist synthetisch geprüft, **die reale Wiederholung dieser Alsergrund-Kachel ist noch ausständig**. Zum Nachtesten:

~~~bash
git pull --ff-only
.venv/bin/python -m scripts.wienwide_street build \
  --manifest data/processed/wienweit/alsergrund/raster.json \
  --input-root data/processed/wienweit/alsergrund/eingaben \
  --out-root data/processed/wienweit/alsergrund/strassenraum \
  --kataster-cache data/cache/kataster \
  --only 'x+000001_y+000342'
~~~


**Realer Alsergrund-Straßenraum, erster Gesamtlauf (14.10.2026):**
Alle **10/10** Kacheln wurden fertig berechnet, die bereits
vorhandene Kachel `x+000001_y+000342` wurde als **geprüfter Cache**
wiederverwendet. Die **aus auf 0,1 m² gerundeten Konsolenausgaben**
summierte Straßenraumfläche beträgt **790.994,1 m²**
(ca. **26,6 %** der rund 2,97 km² Bezirks-AOI). Für die **neun
neu berechneten** Kacheln wurden zusammen **71,19 s**
lokale Rechenzeit protokolliert; die 20,76 s der zuvor
fertiggestellten Pilotkachel sind darin nicht enthalten.
Diese Zeiten umfassen **nicht** die vorherigen FMZK-/BEV-Downloads
oder GIP-Indexierung. Die genauen, ungerundeten Flächen stehen
in den zehn lokalen `street.sqlite`.

Damit sind die echten Straßenraum-Eingaben für den ersten
Bezirks-Voronoi-Test vorbereitet. Die GIP-V0-Flächenzuordnung
und ihre strenge Flächenbilanz sind **noch nicht real
durchgelaufen**. Zunächst nur eine Partitionierungskachel
mit `--limit-tiles 1` ausführen und das Ergebnis prüfen.

### 4. V0 kachelweise rechnen und wiederaufnehmen

~~~bash
.venv/bin/python -m scripts.wienwide_partition \
  --manifest data/processed/wienweit/alsergrund/raster.json \
  --gip-index data/processed/wienweit/alsergrund/gip.sqlite \
  --street-root data/processed/wienweit/alsergrund/strassenraum \
  --out data/processed/wienweit/alsergrund/aufteilung.sqlite \
  --limit-tiles 1

.venv/bin/python -m scripts.wienwide_partition \
  --manifest data/processed/wienweit/alsergrund/raster.json \
  --gip-index data/processed/wienweit/alsergrund/gip.sqlite \
  --street-root data/processed/wienweit/alsergrund/strassenraum \
  --out data/processed/wienweit/alsergrund/aufteilung.sqlite
~~~

Vollständige Kacheln mit unveränderten Prüfsummen werden übersprungen. Die Ausgabe enthält pro Kachel und GIP-ID separate metrische Polygonfragmente und die drei Kategorien ungeklärter Flächen. **PARTIELL** ist nicht gleichbedeutend mit einem fertigen Bezirksresultat.

**Realer Alsergrund-V0-Bezirkslauf, 14.10.2026:**
Mit allen **10 von 10** Straßenraum-Kacheln und dem zentralen
GIP-SQLite-Index wurde `wienwide_partition` vollständig ausgeführt.
Eine bereits berechnete Kachel wurde unverändert per SHA geprüft
und übersprungen.

| Ergebnis | Wert |
| --- | ---: |
| Straßenraum | 790.994,0589567656 m² |
| GIP-Abschnitten zugeordnet | 652.048,846396666 m² (82,43 %) |
| Knotenbereiche, separat | 50.908,654366879775 m² (6,44 %) |
| Sonderachsen, separat | 84.741,46299363286 m² (10,71 %) |
| Nicht zugeordnet | 3.295,0951995779114 m² (0,42 %) |
| Summe ungeklärte Gruppen | 138.945,21256009053 m² (17,57 %) |
| Eindeutige GIP-IDs mit Abschnittsfläche | 586 |
| Kumulierte Partitionierungszeit (10 Kacheln) | 30,627436412978568 s |
| Summenbilanzdifferenz | −0,00000000908 m² |

Die Summenbilanz stimmt im Rahmen numerischer Rundungsfehler;
die Kachelroutine prüft außerdem Überlappungen, Lücken und
außerhalb liegende Fläche je Kachel.

**Fachliche Einordnung:** Die nur 0,42 % wirklich
`nicht_zugeordnet` sind nicht mit den übrigen 17,15 %
gleichzusetzen. Die restlichen Flächen werden **bewusst**
als Knotenbereich (Radius 7 m) und Sonderachse (FOW ≠ 3)
gesondert geführt. Das ist eine gelungene technische
V0-Partitionierung, **keine unabhängige Validierung**
der zugrunde liegenden Straßenraummaske, des amtlichen
GIP-Graphen oder der fachlichen Abschnittszuordnungen.
Als nächste Schritte: Benchmarkdatei speichern,
Sonderachsen nach FOW aufschlüsseln, Knotenradien und
ungeklärte Restflächen räumlich in QGIS/Kartensammlung
kontrollieren und erst danach Parameter-/Methodikänderungen
in Betracht ziehen.

### 4a. QA-GeoPackage für QGIS und Kartensammlung

Nach der vollständigen GIP-V0-Partition kann **ohne erneute Berechnung**
ein GeoPackage aller Flächen in **EPSG:31256** erzeugt werden. Exportiert
werden die bestehenden WKB-Polygone direkt; es gibt **keinen WGS84-
GeoJSON-Rückweg** und keine Veränderung der Zuordnungsregel.

~~~bash
git pull --ff-only

.venv/bin/python -m scripts.wienwide_qa_gpkg \
  --manifest data/processed/wienweit/alsergrund/raster.json \
  --gip-index data/processed/wienweit/alsergrund/gip.sqlite \
  --street-root data/processed/wienweit/alsergrund/strassenraum \
  --partition-db data/processed/wienweit/alsergrund/aufteilung.sqlite \
  --out data/processed/wienweit/alsergrund/alsergrund_qa.gpkg
~~~

Das GeoPackage besitzt genau **vier räumliche Layer**:

| Layer | Inhalt und wichtigste Attribute |
| --- | --- |
| `gip_abschnitte` | Zugeordnete Fläche je **Kachel × GIP-ID**; `gip_id`, `strassenname`, `fow` (derzeit 3), `knoten_von`, `knoten_nach`, `flaeche_m2`, `gip_gesamt_m2` |
| `knotenbereiche` | Kachelweise vereinigte Bereiche um Knoten (7-m-Radius), `kachel_id`/`flaeche_m2` |
| `sonderachsen` | Kachelweise vereinigte Flächen der FOW-ungleich-3-Achsen, `kachel_id`/`flaeche_m2` |
| `nicht_zugeordnet` | Nach der V0-Partition nicht zugeteilte Restflächen, `kachel_id`/`flaeche_m2` |

Alle Geometrien sind **MultiPolygon**, direkt im metrischen CRS, mit
**GeoPackage-RTree-Raumindex** pro Layer. Die GIP-Flächen werden bewusst
**nicht über Kachelgrenzen dissolved**; mehrere Zeilen mit derselben
`gip_id` sind Teile desselben globalen Abschnitts. Die Spalte
`gip_gesamt_m2` enthält bereits die Summe dieser Teile über alle Kacheln.

Das GeoPackage enthält außerdem die **nicht räumliche Tabelle**
`qa_provenienz` mit den SHA-256-Werten von Manifest, GIP-Index,
Partition und sämtlichen Straßenraum-Eingaben sowie dem vollständigen
V0-Flächenbilanzbericht. Der Export akzeptiert nur eine **vollständige**
Partition mit passenden Quelle-Prüfsummen, gültigen Geometrien,
Kachelschnitt und kontrollierter Flächenbilanz. Er schreibt
atomar (erst `.gpkg.tmp`, dann das fertige `.gpkg`) und
**überschreibt niemals** ein bestehendes QA-GeoPackage.

**Wesentliche fachliche Grenze:** Die V0-Partition hat alle
Sonderachsen pro Kachel zu einer Sammelfläche vereinigt.
Deshalb können im bestehenden Ergebnis **keine verlässlichen
Sonderachsen-GIP-IDs oder einzelnen FOW-Werte** angezeigt werden.
Eine echte FOW-Statistik pro Achse würde Änderungen an
`wienwide_partition` und eine neue V0-Aufteilung erfordern.
Auch die Knotenbereiche sind im V0-Ergebnis nicht einzelnen
GIP-Knoten-IDs zugeordnet.

**Sichtung:** Alle vier GeoPackage-Ebenen in QGIS oder
Kartensammlung öffnen, ein aktuelles Orthofoto darunterlegen,
`nicht_zugeordnet` zuerst auf mögliche systematische Restlücken
kontrollieren, danach die großen `sonderachsen` und
`knotenbereiche`. Die Polygonattribute mit `kachel_id` und
`gip_id` erlauben eine gezielte Rücksuche in den Rohdaten.
Ein erfolgreicher Export beweist die **technische** Flächenkonsistenz,
nicht die fachliche Richtigkeit jeder Straßenzuordnung.

**Erster realer QA-GeoPackage-Export (14.10.2026):**
`data/processed/wienweit/alsergrund/alsergrund_qa.gpkg` wurde
aus der vollständigen Bezirksaufteilung erfolgreich erzeugt.
Die CLI lieferte folgende **tatsächlich ermittelten** Ergebnisse:

| Räumlicher Layer | Features | Fläche m² | Anteil Straßenraum |
| --- | ---: | ---: | ---: |
| `gip_abschnitte` | 662 | 652.048,8463966663 | 82,43 % |
| `sonderachsen` | 9 | 84.741,46299363286 | 10,71 % |
| `knotenbereiche` | 10 | 50.908,65436687977 | 6,44 % |
| `nicht_zugeordnet` | 10 | 3.295,095199577912 | 0,42 % |
| **Gesamt** | **691** | **790.994,0589567656** | **100 %** |

Flächenbilanzdifferenz gegenüber Straßenraum:
**−9,0803951025 × 10⁻⁹ m²**. Die 662
Abschnittsfeatures sind Kachelfragmente von
**586 eindeutigen GIP-IDs** (aus dem vollständigen V0-Bericht).
Alle zehn Bezirkskacheln sind enthalten.
**Dies ist der erste reale erfolgreiche GeoPackage-Export,
aber noch keine fachliche Ortskontrolle der Einzelpolygone.**

Zur ersten Sichtprüfung in QGIS die vier Layer laden,
insbesondere `sonderachsen` und `nicht_zugeordnet`
mit kontrastierenden Farben über Orthofoto und GIP-Achsen legen.
In QGIS lassen sich die großen Sammelgeometrien über die
Attributtabelle nach `flaeche_m2` absteigend sortieren.
Da `sonderachsen` derzeit **je Kachel** aggregiert ist, sind
9 Features **nicht** 9 GIP-Sonderachsen; zur Zuordnung nach FOW
ist eine separate Weiterentwicklung des Partitionsmoduls nötig.
`knotenbereiche` und `nicht_zugeordnet` sind ebenfalls
je Kachel gesammelte Multipolygone, die viele disjunkte
Kleinflächen enthalten können.

### 5. Benchmark protokollieren

~~~bash
.venv/bin/python -m scripts.wienwide_benchmark \
  --manifest data/processed/wienweit/alsergrund/raster.json \
  --inputs data/processed/wienweit/alsergrund/eingaben \
  --gip-fragments data/processed/wienweit/alsergrund/gip_fragmente \
  --street-root data/processed/wienweit/alsergrund/strassenraum \
  --gip-index data/processed/wienweit/alsergrund/gip.sqlite \
  --partition-db data/processed/wienweit/alsergrund/aufteilung.sqlite \
  --out data/processed/wienweit/alsergrund/benchmark.json
~~~

Anschließend denselben Ablauf mit eigener AOI und getrennten Pfaden für Donaustadt durchführen. Erst nach beiden echten Durchläufen lassen sich Speicherbedarf, Quellverfügbarkeit, Flächenbilanz und Laufzeiten vergleichen.

## Qualitäts- und Skalierungsgrenzen

- Die Voronoi-Ergebnisse werden pro Kachel gegen den Original-Straßenraum geprüft. Gemeinsam verwenden sie **globale GIP-Stützpunkte**, sodass selbst an einer Kreuzung auf der Kachelgrenze dieselbe Flächenzuordnung wie in einem globalen V0-Lauf entstehen soll. Die synthetischen Regressionen prüfen die Übereinstimmung mit der bisherigen V0; **Realtest steht aus**.
- Alle Kacheln sind auf die AOI-Kerne beschnitten; keine Übertragung einer 75-m-Halo-Fläche in die endgültige Flächenbilanz.
- GIP-ID-Dubletten mit abweichender Geometrie führen zu einem Fehler. Nichts wird mit einer neuen ID ersetzt.
- Der Quellstand muss konsistent sein. Die Katalog-/Daten-SHA werden zwischen Läufen geprüft. Wegen WFS-Änderungen während eines sehr langen Abrufs bleibt eine **zeitliche Snapshot-/Änderungsprüfung vor dem endgültigen Wien-Lauf** erforderlich.
- Die bisherige Katasteranalyse nutzt BEV-z16 mit Grenzwerten für Kacheln und Grundstücke. Sie muss bei schwierigen Pilotkacheln anhand echter Fälle weiter abgesichert werden.
- Der Benchmark-Zeitwert bezieht sich **nur auf lokale Voronoi-Partitionierung samt Kachel-Lesen**, **nicht** auf sämtliche FMZK-/BEV-/GIP-Downloads oder Kronenmethoden.
- Baumkronen A/B/C und Bodenbegrünung je GIP-ID **wienweit berechnen**, insbesondere GRM-WMS kachelweise korrekt in metrischer Auflösung zu verwenden, ist ein **nächster eigener Schritt**. Die bestehende GRM-Maske ist nur für kleine Rastergrößen ausgelegt.
- **Keine** fertige Kartenkachel-/MBTiles-Erzeugung oder automatische Gartenstraßen-Klassifizierung in diesem Schritt.

Die bisherigen 45 Testabschnitte und ihre Kennzahlen bleiben unverändert. Rohdaten liegen lokal unter data/ (Git-ignored) und gehören nicht in das öffentliche Repository.
