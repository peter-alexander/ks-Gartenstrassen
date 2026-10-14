# Modul 5 – Straßenabschnitte als Bezugsräume

**Beschlossener Zwischenstand 14.10.2026: V0 mit kreisförmigen Kreuzungsbereichen (7 m) ist die vorläufig maßgebliche Straßenabschnittsbildung. Der reale lokale V0-Lauf und die numerische Flächenbilanz sind geprüft, die räumliche Zuordnung bleibt fachlich vorläufig. V1/V1.1/V1.2-Eckpunktversuche sind pausiert; keine Integration und keine weitere Optimierung, bis der Nutzer einen früheren Kreuzungsalgorithmus geprüft hat.**

## Ziel und Abgrenzung

Die bisherige, vorläufige Straßenraumfläche (Modul 2) und die unabhängigen
Kennzahlen Bodenbegrünung (Modul 3) und Kronenüberschirmung (Modul 4)
sollen künftig **pro Straßenabschnitt zwischen Kreuzungen** ausgewertet werden.
Die Abschnittsbildung ist ein eigenes Modul, keine neue Straßenraum-Erkennung
und keine neue Baumkronen-Klassifikation.

Für den bekannten Testausschnitt beträgt die Straßenraumfläche 46.630,56 m².
Bodenbegrünung: 889,18 m² / 1,91 %. Kronenüberschirmung (unterschiedliche
Referenzmethoden): A 3.647,05 m² / 7,82 %, B 3.678,65 m² / 7,89 %,
C 4.358,69 m² / 9,35 %. Diese Gebietssummen werden nicht auf einzelne
Abschnitte „verteilt“, sondern künftig durch echten geometrischen
Schnitt mit deren **exklusiven Flächen** neu ermittelt.

Methode D bleibt unverändert: Der Vegetationsindikator bei Schwelle **0,20
ist die Baseline**; die Unterscheidung von Baumkronen und sonstiger Vegetation
ist **offen**. Seine 10,58 % Vegetationsfläche im Teststraßenraum dürfen
nicht als Baumkronenüberschirmung verwendet werden.

## 1. Abschnittsreferenz: amtlicher Wiener GIP-Straßengraph

Primärquelle: **Intermodales Verkehrsreferenzsystem (GIP.at) Straßengraph Wien**
der Stadt Wien, OGD / CC BY 4.0:

- **`ogdwien:STRASSENGRAPHOGD`** – Linien der bereits definierten
  Straßenabschnitte. Die amtliche Definition lautet: Teil einer Straße
  zwischen zwei Kreuzungen, normalerweise entlang der Straßenachse.
- **`ogdwien:STRASSENKNOTENOGD`** – Netzknoten, gewöhnlich in
  Kreuzungsmittelpunkten.
- **`GIP_OBJECTID`** als Quell-ID des Abschnitts, **`FEATURENAME`** /
  **`REG_STRNAME`** als Beschriftung, zusätzliche Netzattribute zur
  späteren fachlichen Differenzierung (z. B. `FOW`, `FRC`,
  `EDGECATEGORY`, `DEDICATEDWIDTH`).

Quelle: https://www.data.gv.at/datasets/1039ed7e-97fb-435f-b6cc-f6a105ba5e09

Der amtliche Graph umfasst die dokumentierten öffentlichen Verkehrsflächen.
Er ist **keine rechtlich verbindliche Straßenraum-Polygonbegrenzung**.
Linien allein liefern insbesondere keine eindeutige Gehsteig-, Platz- oder
Kreuzungsfläche. `DEDICATEDWIDTH` wird nicht als exakt vermessene
Straßenbreite angenommen.

Der vorhandene FMZK-/Kataster-Straßenraum aus Modul 2 bleibt der **einzige
geometrische Flächennenner**. Abschnittslinien definieren nur die
Untergliederung. OSM-Straßenachsen werden nicht gleichzeitig mit GIP
vermengt; sie wären allenfalls ein ausdrücklich eigener späterer
Alternativprovider.

## 2. Getrennter Datenbeschaffungs-Schritt (implementiert; lokaler Realtest offen)

Der Adapter `scripts/fetch_gip_sections.py` stellt für das vorhandene
FMZK-Testgebiet plus standardmäßig **75 m Randbereich** zwei
**BBOX-begrenzte WFS-GeoJSON-Abrufe** bereit, analog zum bestehenden
`scripts/fetch_vienna_trees.py`. Dabei:

1. Quellumfang aus dem FMZK-Ausschnitt ableiten, in **EPSG:3857**
   abfragen und als **EPSG:4326** ausgeben; die Achsenreihenfolge
   über gültige Wiener Koordinaten und die Lage im Testgebiet prüfen.
2. Abschnitts- und Knoten-Features getrennt speichern;
   `GIP_OBJECTID`, Geometrietyp, eindeutige Kennung, BBOX-Bezug
   und leere/ungültige Geometrien kontrollieren.
3. Abrufgrenzen und unvollständige WFS-Antworten **erkennen statt
   schweigend als vollständig zu übernehmen**. Quell-URLs, Datum,
   Umfang und SHA-256 protokollieren. Kein Wien-Gesamtdownload.
4. Ausgangsdaten lokal unter `data/processed/strassenabschnitte/`
   speichern, ohne die vorhandenen Module oder Rohdaten zu ändern.

**Offline/Online-Aufruf (nur vorhandenes Testgebiet):**

```bash
git pull --ff-only
.venv/bin/python -m scripts.fetch_gip_sections
```

Standardausgabe unter `data/processed/strassenabschnitte/gip/`:

| Datei | Inhalt |
| --- | --- |
| `gip_strassengraph_wfs.geojson` | Originalantwort Straßenachsen, unverändert |
| `gip_strassenknoten_wfs.geojson` | Originalantwort Kreuzungsknoten, unverändert |
| `abschnitte_achsen.geojson` | Karten-Prüflayer: Achsen, IDs, Namen und Netzattribute |
| `abschnitte_knoten.geojson` | Karten-Prüflayer: Knoten, IDs und ergänzende Attribute |
| `gip_probe_bericht.json` | Abfrage-URLs, BBOX, GeoJSON- und ID-Prüfung, SHA-256, Duplikate, Objektstatistik |

Für die **Kartensammlung** die beiden `abschnitte_*.geojson` importieren;
die Rohantworten daneben aufbewahren. Diese Layer besitzen **noch keine
Straßenraumflächen**.

Der Standard verweigert ab **4.000 Features pro Layer** eine potenziell
abgeschnittene Antwort, zusätzlich bei WFS-`totalFeatures`/
`numberMatched` größer als der Antwortzahl, leerer Antwort,
fremdem CRS, ungültigen Geometrien oder Objekten außerhalb der BBOX.
Doppelungen von `GIP_OBJECTID` sind ausdrücklich im Bericht,
werden **nicht** automatisch dedupliziert. Der Abruf ist auf 30 MB
pro Layer begrenzt.

**Wiederholung:** Der zweite gleiche Aufruf verwendet die SHA-geprüften
Original-GeoJSONs aus dem Cache ohne Netzwerk. Mit `--offline` lässt
sich dieser Modus erzwingen. Ein bewusst neuer Abruf erfordert
`--refresh`; für einen unabhängigen Vergleich besser
`--out-dir data/processed/strassenabschnitte/gip_test2` setzen.
Ein geänderter FMZK-Ausschnitt oder geänderte Abrufparameter werden
beim Cachevergleich abgewiesen. Eine unterbrochene/teilweise Ausgabe
wird nicht als fertiger Datensatz akzeptiert.

### Erster realer Datenlauf (14.10.2026)

Die lokal erzeugten und zur Prüfung bereitgestellten
`gip_probe_bericht.json`, `abschnitte_achsen.geojson` und
`abschnitte_knoten.geojson` wurden gemeinsam geometrisch geprüft.

| Ergebnis | Befund |
| --- | ---: |
| Straßengraph (LineString) | **80 Achsen** |
| Straßenknoten (Point) | **47 Knoten** |
| Doppelte GIP-IDs und WFS-Feature-IDs | **0** |
| Referenzierte Knoten-IDs | **64** |
| Im Knotendatensatz vorhandene referenzierte IDs | **47** |
| Im Knotenabruf nicht enthaltene IDs | **17** |
| Linienenden mit abgerufenem Knoten | **140 / 160** |
| Metrische Distanz der 140 verknüpften Endpunkte | **0 m** |
| Endpunkte ohne geladenen Knoten | **20**; **alle außerhalb** der angefragten WFS-BBOX |
| Achsen mit Kontakt zum ursprünglichen Testrechteck | **45** |
| Knoten innerhalb des ursprünglichen Testrechtecks | **22** |
| Zusammenhangskomponenten (nach Knoten-IDs) | **4**: 74, 3, 2, 1 Achsen |

Die 17 fehlenden IDs sind **kein Topologiefehler**: Ihre 20
zugehörigen Linienenden liegen vollständig außerhalb der WFS-Anfrage-BBOX
mit 75 m Zusatzrand. Dies wurde geometrisch in EPSG:3857 geprüft;
die Lage aller verfügbaren Knoten stimmt mit dem zugehörigen
GIP-Linienende in EPSG:31256 exakt überein. Die 45/22-Teilmengen
beziehen sich **nur auf das ursprüngliche geografische Rechteck**,
nicht auf die vereinigten Modul-2-Straßenraumflächen.

**Separierte Teilnetze:** Hauptgraph (74 Achsen),
Karoline-Tintner-/Olga-Misař-Promenade (3),
Siemens-Nixdorf-Steg (2) und Ari-Rath-Platz (1).
Das sind zunächst nur topologische Komponenten im begrenzten
GIP-Ausschnitt. Ob und wie sie zur Gartenstraßenanalyse gehören,
muss anhand von Verkehrsart, Geometrie und Lage geprüft werden.

Die Quellattribute enthalten verschiedene `FOW`-Werte (3/15/14/2/18)
und `EDGECATEGORY`-Werte (G/L/B); **noch kein automatischer Filter**
für Straßen, Fußwege, Brücken oder Promenaden. Der numerische
`DEDICATEDWIDTH` ist keine vermessene Polygonbreite: **63 von 80 Achsen**
tragen im ersten GIP-Abruf den Wert **−1**. Deshalb ist eine
Flächenaufteilung durch einfaches Puffern der GIP-Achsen mit diesem
Breitenattribut nicht tragfähig. Negative bzw. fehlende Werte müssen
ausdrücklich kenntlich bleiben.

### Wiederholbare lokale Topologieprüfung

Zusätzlich steht nun `scripts/analyze_gip_topology.py` bereit. Es
prüft die Beziehungen der realen Knoten-IDs zu den Endpunkten,
unterscheidet fehlende Knoten **innerhalb** und **außerhalb**
der Anfrage-BBOX, ermittelt Teilnetze und meldet Endpunktabweichungen.
Das Skript verändert keine der geladenen GeoJSONs.

```bash
git pull --ff-only
.venv/bin/python -m scripts.analyze_gip_topology
```

Ausgabe: `data/processed/strassenabschnitte/gip/gip_topologie_bericht.json`.
Ein schon vorhandener Bericht wird nicht überschrieben (alternativ
`--out <neuer-pfad>`). Die Prüfung selbst ist offline;
die GitHub-Tests verwenden synthetische Daten.

**Fachlich weiterhin zu prüfen:** Linienführung an echten Kreuzungen,
getrennte Fahrbahnen, Straßenbahnanlagen, Sackgassen, Randabschnitte
und die Sonderfälle der drei kleinen Teilnetze. Insbesondere
nicht behaupten, dass GIP-Teilnetze identisch mit den zu bildenden
Straßenraum-Polygonabschnitten sind. Eine fehlende Knotenreferenz
innerhalb der Anfrage-BBOX wäre ein tatsächlicher Hinweis zur
Nachprüfung. Ohne Flächenzuordnung noch keine Abschnittsquoten.

## Festlegung: V0 bleibt in Verwendung (14.10.2026)

**Vorläufig maßgebliche Methode:** `scripts/assign_gip_section_areas.py`
mit **kreisförmigen Kreuzungsbereichen, 7 m Radius**. Die GIP-Achsen
bleiben Grundlage der exklusiven Zuordnung außerhalb dieser
Knotenflächen. Kreuzungen, Sonderachsen und Restflächen werden
getrennt ausgewiesen. Die ursprüngliche Straßenraummaske und
die geprüfte Flächenbilanz bleiben erhalten.

**Kein funktionaler Rückbau erforderlich:** Die V1-Kreuzungsdiagnose
ist ein eigenständiges Skript und wurde **nicht** in die
V0-Straßenabschnittsbildung eingebaut. Der Nutzer hat entschieden,
sie **vorerst nicht weiterzuentwickeln**. Möglicherweise existiert
bereits ein früher ausgearbeiteter Algorithmus; erst nach dessen
Sichtung erneut über die Kreuzungsgeometrie entscheiden.
Keinen der experimentellen Schnitte in die aktive V0-Aufteilung
übernehmen. Bisherige Diagnose-Skripte und Berichte zu Vergleichszwecken
behalten, aber nicht als produktive Abschnitte verwenden.

## Dokumentierter, derzeit pausierter Entwurf für präzisere Kreuzungsgrenzen (v1)

Auf Basis der Nutzer-Skizze wird eine **eck-/übergangspunktbasierte
Kreuzungsabgrenzung** untersucht: an jedem Kreuzungsarm die beiden
Übergänge von der Aufweitung zum normalen Straßenquerschnitt bestimmen,
daraus eine **Querlinie** bilden und erst danach die mittlere
Kreuzungsfläche trennen. Anders als v0 basiert dies nicht pauschal
auf einem 7-m-Radius. Die 7-m-Methode bleibt als explizit
gekennzeichneter Fallback und Vergleich erhalten.

**Konkreter Algorithmus, Randfälle, Geometrieprüfung,
Abnahmekriterien und Umsetzungsschritte:**
[Modul 5 – Eckpunkt-Erkennung an Kreuzungen](Modul-5-Eckpunkte-Kreuzungen.md).
**Status: pausiert.** Diagnose-Prototyp
`scripts/diagnose_gip_junction_corners.py` wurde mit lokalen
Straßenraum-/GIP-Daten in mehreren Varianten tatsächlich getestet.
Die Schnittlinien bleiben **unvalidierte Kandidaten** und wurden
**niemals in V0 integriert**. Keine weitere Entwicklung geplant,
bis der früher eventuell vorhandene Kreuzungsalgorithmus geprüft ist.

**V1.1-Diagnose:** Für T-Kreuzungen ist die **rechtwinklige
Schnittlinie** mit einem einseitigen Übergang als Fallback
implementiert. Der Referenzrand ist zwischen äußerem
Straßenraum (`hauswand`, Standard) und einer **vereinigten FMZK-Verkehrsflächen 21/30/32/33/39**
(`gehsteigkante`, einschließlich Zebrastreifen, Schwellen,
Parkspuren und sonstiger Verkehrsflächen) umschaltbar.
Ergebnisse sind weiterhin nur **unvalidierte Kandidaten**,
keine abgegrenzten neuen Kreuzungspolygone oder geänderten
Abschnittsflächen. [Varianten und Aufruf](Modul-5-Eckpunkte-Kreuzungen.md#v11-t-kreuzungen-und-alternative-gehsteigkante-14102026).

**V1.2-Diagnose:** Die zuvor zu weit außen liegenden Schnitte
werden jetzt an der **inneren Schulter der Ohrwaschln** gesucht,
mit explizitem äußerem Fallback und gemeinsam genutzter
Verkehrsflächen-Maske für **beide** Randvarianten.
FMZK-Gebäude 11/19 werden als eigene Kontur- und
Abstandsdiagnose verwendet, nicht als automatisch
gültige Schnittlinie. **Zwei reale V1.2-Diagnoseläufe liegen vor;
die Ergebnisse sind weiterhin nicht fachlich bestätigt und
die V1-Entwicklung ist pausiert.**
[Methodik und Aufruf](Modul-5-Eckpunkte-Kreuzungen.md#v12-beginn-statt-ende-der-ohrwaschln--beide-referenzen-14102026).

## 3. Aus Graphlinien exklusive Straßenraumflächen gewinnen (erste experimentelle Implementierung)

Die eigentliche neue Aufgabe ist die **flächentreue, überschneidungsfreie
Zuordnung** von Modul-2-Polygonen zu GIP-Abschnitten.

**Erster implementierter geometrischer Versuch** (keine fachlich endgültige Methode):

1. Straßenraumgeometrie vereinigen und sämtliche Rechnungen in
   **EPSG:31256** durchführen.
2. GIP-Achsen einschließlich der Anschlusskanten außerhalb der
   Test-BBOX als Kandidaten verwenden; Linienenden am Testgebietsrand
   ausdrücklich als `rand_abgeschnitten` behandeln.
3. Ein flächiges, gegenseitig **exklusives** Zuordnungsverfahren auf
   Basis der Achslage (z. B. linienbezogene Distanzaufteilung) mit
   alternativen Regeln für Knoten-/Kreuzungsbereiche **testen**.
   **Nicht** einzelne Achsen pauschal mit `DEDICATEDWIDTH/2`
   puffern: Dabei entstehen Lücken, Überlappungen und falsch
   verteilte Gehsteige.
4. Mehrdeutige Kreuzungs-, Platz- und parallel geführte Bereiche
   nicht stillschweigend zuweisen: erst als **eigene Prüfklasse
   `knotenbereich`/`ungeklaert`** protokollieren. Eine spätere
   Verteilung auf Abschnitte braucht eine explizite und getestete Regel.
5. Restflächen ohne zugehörige GIP-Achse getrennt erfassen;
   sie dürfen weder verschwinden noch als „keine Straße“ gelten.

### Experimenteller Lauf `assign_gip_section_areas.py`

Das neue Modul liest **rein lokal** die geprüften GIP-Karten-GeoJSONs,
`gip_probe_bericht.json`, `fmzk_test.gpkg` und **genau dieselbe**
`fmzk_strassenraum.geojson` wie die bisherigen Modul-3/4-Messungen.
Es verändert keine Eingabedateien und ruft keine Webdienste ab.

```bash
git pull --ff-only
.venv/bin/python -m scripts.assign_gip_section_areas
```

Standardausgabe: `data/processed/strassenabschnitte/aufteilung_v0/`

| Datei | Inhalt |
| --- | --- |
| `abschnitte_flaechen.geojson` | Experimentell zugeordnete Straßenraum-Teilpolygone mit `gip:<GIP_OBJECTID>`, Name, FOW und m² |
| `abschnitte_ungeklaert.geojson` | Separate Polygonflächen mit `status=knotenbereich`, `sonderachse` oder `nicht_zugeordnet` |
| `abschnitte_bericht.json` | Straßenraum-Gesamtfläche, zugeteilt/ungeklärt, Anzahl Abschnitte, Flächenbilanz, Parameter, SHA-256 |

**Methode:** Linien alle **5 m** im metrischen EPSG:31256-Raum
abstützen, darauf ein geometrisches Voronoi-Zellnetz aufbauen und die
Zellen **mit der originalen vereinigten Straßenraummaske schneiden**.
Lücken oder Überlappungen werden nicht durch Pixelzählen geschätzt.
Die Knoten mit GIP-Grad **≥ 3** werden innerhalb eines vorläufigen
Radius von **7 m** zuerst als eigene **Kreuzungs-Prüfflächen**
ausgeschnitten. Jedem übrigen Flächenanteil kann maximal die nächste
Straßenachse zugeordnet werden, solange die Fläche innerhalb
**25 m Achsabstand** liegt. **Nur FOW = 3** gilt dabei vorläufig
als normaler Straßenabschnitt. Flächen, die Voronoi-Zellen anderer
Wegtypen zugeordnet wären, heißen `sonderachse`; alle übrigen
`nicht_zugeordnet`.

**Diese Grenzwerte sind technische Erstannahmen und müssen an den
tatsächlichen Straßenabschnittspolygonen geprüft werden.** Es ist
noch keine amtliche Breitenmessung, keine exakte Gleichabstandszone
zu Liniensegmenten und keine korrekte Kreuzungsgrenze.
Besonders bei parallelen Fahrbahnen, Gehsteigen, Wegen oder
schrägen Kreuzungen können Voronoi-Grenzen unplausibel sein.
Aus `DEDICATEDWIDTH=-1` wird ausdrücklich keine Straßenbreite
geschätzt. Bei Stützpunkt-Duplikaten wird statt einer willkürlichen
Zuweisung abgebrochen.

**Kontrollen:** Jeder Abschnitt und jede ungeklärte Klasse wird
geometrisch von den übrigen getrennt. Der verbleibende Rest wird
**immer als Fläche ausgewiesen**, nicht verworfen. Vor dem Export
werden Summe, geometrische Vereinigungsfläche, Überlappung, Lücke
und Außenanteil mit einer Flächentoleranz von
`max(0,05 m²; 10⁻⁶ × Straßenraumfläche)` geprüft. Bei
verletzter Invariante scheitert der Lauf **ohne Ausgabe**.
Ein existierender Ergebnisbericht oder GeoJSON wird nicht
überschrieben: Für Varianten ein neues `--out-dir` wählen.

Optionale experimentelle Parameter:
`--sample-spacing-m`, `--node-radius-m`,
`--max-axis-distance-m`. Eine Variation verlangt getrennte
Ausgabeverzeichnisse und einen nachfolgenden Flächen- und
Sichtvergleich. Nicht als automatisch optimierbare Parameter
interpretieren.

Die Dokumente aus diesem ersten Versuch sind zur Sichtkontrolle in
Kartensammlung/QGIS vorgesehen. Erst nach dem **echten lokalen Lauf**
und der Prüfung der 46.630,56-m²-Bilanz sollen wir einzelne
Zuordnungsregeln (insbesondere die Kreuzungsbehandlung) verbessern.

**Bilanz-Invariante:** Summe der geometrisch vereinigten,
sich nicht überlappenden Abschnittsflächen **plus** gesonderte
Knoten- und ungeklärte Restflächen = gesamte Modul-2-Straßenraumfläche.
Die Summe der Einzelflächen darf nicht wegen gemeinsamer Kreuzungsflächen
größer werden. Ein `status` je Fläche zeigt an, ob die Zuordnung
verlässlich, randbedingt oder ungeklärt ist.

### Reales Ergebnis der Flächenpartition (14.10.2026, 11:31 UTC)

Der erste **lokale** Bericht `abschnitte_bericht.json` zur
`aufteilung_v0` ist eingegangen. Als Quelldokumente sind
`fmzk_strassenraum.geojson` mit SHA-256
`dc53cd78d0bcd5cb242529e126a969f1be6ca5d27487ff1e85ee684654d7fc11`
sowie die zuvor abgefragten GIP-Achsen/-Knoten ausgewiesen.
Parameter unverändert: 5 m Stützpunktabstand, 7 m Knotenradius,
25 m maximale Achsdistanz, FOW 3.

| Kategorie | Fläche | Anteil an 46.630,56 m² |
| --- | ---: | ---: |
| 45 experimentell zugeordnete Abschnitte | **43.217,91 m²** | **92,68 %** |
| Ungeklärte Kreuzungsflächen | **3.368,09 m²** | **7,22 %** |
| Ungeklärte Sonderachsen | **44,56 m²** | **0,10 %** |
| Nicht zugeordneter Rest | **~0,000000002 m²** | **~0 %** |
| **Gesamt** | **46.630,56 m²** | **100 %** |

Der Bericht enthält 80 Quellachsen, **38 Knotengrad-≥3-Kreuzungen**
und **1.592 Voronoi-Stützpunkte**. Unter den verbleibenden
3.412,65 m² ungeklärter Flächen sind **98,69 % Kreuzungsbereiche**.
Die technische Flächenbilanz ist konsistent:
`bilanzdifferenz_m2 = 7,64e-10`,
`ueberlappung_m2 = 2,69e-10`, `fehlend_m2 = 0`,
`ausserhalb_m2 = 0`. Damit ist die Bilanzinvariante numerisch erfüllt
– **nicht** bereits die Lage- und Zuordnungsqualität.

**Fachliche Interpretation:** Der gesamte Straßenraum konnte
rechnerisch abgedeckt werden, weil nicht zuweisbare Flächen
gesondert erhalten bleiben. Dass `nicht_zugeordnet` fast null ist,
beweist **keine** korrekte Zuordnung: Das Ergebnis hängt auch vom
25-m-Achsabstand und der Voronoi-Konstruktion ab. Insbesondere die
**3.368 m² pauschal ausgeschnittenen Knotenzonen** dominieren die
noch ungeklärte Fläche. Der Knotenradius 7 m darf daher nicht nur
wegen eines hohen Zuordnungsprozents reduziert werden.

**Nächster Prüfpunkt:** Die beiden tatsächlichen Ausgabe-GeoJSONs
`abschnitte_flaechen.geojson` und `abschnitte_ungeklaert.geojson`
gegen GIP-Achsen und Orthofoto überprüfen, zuerst die
Kreuzungszonen, danach breite Straßen, parallele Achsen, Promenaden,
Steg und abgeschnittene Randbereiche. **Keine Schwellenveränderung,
keine Übernahme als validierte Abschnitte und keine abschnittsweisen
Begrünungs-/Überschirmungsquoten vor dieser Geometrieprüfung.**

## 4. Vorgesehene Ausgabe-Schnittstelle

- `abschnitte_achsen.geojson` – amtliche Quelllinien zur visuellen
  Kontrolle in der Kartensammlung.
- `abschnitte_flaechen.geojson` – ausschließlich **zugeordnete**
  Straßenraum-Teilpolygone, EPSG:4326, stabile ID z. B.
  `gip:<GIP_OBJECTID>`, Name, Quell-ID, Zuordnungsstatus;
  geometrische Berechnung in EPSG:31256.
- `abschnitte_ungeklaert.geojson` – Knoten-/Restflächen
  und unzureichend eindeutige Zuordnungen, nicht verschwiegen.
- `abschnitte_bericht.json` – Flächenbilanz, Überlappungs-/Lückenprüfung,
  Zahl und IDs betroffener Abschnitte, Quellen und SHA-256 der
  Straßenraum-Eingabe.

Noch **keine** endgültige Feld-/Dateischema-Version. Die später
implementierten Schnittstellen müssen unabhängig von konkreten FMZK-
Attributen sein, analog zum bestehenden Vertrag von Modul 2.

## 5. Prüfung und anschließende abschnittsweise Kennzahlen

Vor einer Übernahme: Kartensammlung-Kontrolle der Abschnittsgrenzen,
Kreuzungen, Straßen mit Mittelstreifen, Plätze, Sackgassen und
Randanschnitte. Zusätzlich automatisiert prüfen:

- keine mehrfach gezählten Straßenraumflächen;
- keine stillschweigend verworfenen Polygonflächen;
- identischer Straßenraum-Nenner wie Modul 2 (innerhalb dokumentierter
  numerischer Toleranz);
- reproduzierbare Zuordnung zu Quell-GIP-IDs und dokumentierter
  Datenstand;
- alle externen Geodaten bleiben optional und sind nicht Bestandteil
  der GitHub-Actions-Tests.

Erst danach können die bestehenden Grün- und Kronengeometrien **pro
Abschnitt** geschnitten und die jeweiligen `m²` und Anteile ausgewiesen
werden. Gesamtwerte dürfen nicht aus Prozentanteilen gemittelt werden;
insbesondere Bodenbegrünung und Baumkronenüberschirmung bleiben
verschiedene, sich potenziell überlagernde Kennzahlen.

## Modul 6 – integrierte Abschnittskennzahlen

Das Offline-Skript `scripts/measure_sections.py` liest die
bestehenden V0-Abschnitts- und Kreuzungsflächen und berechnet
Bodenbegrünung (FMZK 58/69) und Kronenüberschirmung A/B/C
je Teilpolygon. Seine strikte Gebiets- und Methodenbilanz
schließt auch sämtliche noch ungeklärten Flächen ein.
**Die Implementierung ist fertig, der lokale Realtest ausständig.**
Das Skript ändert keine V0-Geometrie, Kreuzungskreise oder
FMZK-/Kronen-Quelldaten.
[Ausführung und Ausgabeformat](Modul-6-Abschnittskennzahlen.md).

## Nächste konkrete Arbeit

**Der erste reale Offline-Lauf ist abgeschlossen und numerisch geprüft:**
92,68 % zugeordnete Straßenraumfläche in 45 Abschnitten;
7,32 % ungeklärt, fast vollständig Kreuzungszonen. **Jetzt die
beiden Ausgabe-GeoJSONs** in der Kartensammlung gegen Orthofoto,
GIP-Achsen und Kreuzungsknoten kontrollieren.
Insbesondere die drei kleinen Netzkomponenten, breite Kreuzungen,
parallele Fahrbahnen und Randabschnitte fachlich überprüfen.
**Kreuzungsalgorithmus nicht weiter verändern**; der Nutzer prüft
zunächst einen eventuell bereits früher entwickelten Ansatz.
Die V0-Flächen als vorläufige Bezugsräume nutzen und vor
verbindlichen Abschnittskennzahlen die wesentlichen
räumlichen Zuordnungen kontrollieren. Noch keine fachlich
vollständig validierten Abschnittsflächen oder Abschnittskennzahlen.
