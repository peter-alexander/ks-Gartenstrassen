# Modul 5 – Straßenabschnitte als Bezugsräume

**Stand 14.10.2026: kleinräumiger GIP-Abruf erfolgreich mit echten Daten geprüft; unabhängiges Topologie-Audit implementiert. Visuelle Kontrolle und Straßenabschnittsflächen noch offen.**

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
`DEDICATEDWIDTH` ist keine vermessene Polygonbreite; negative
bzw. fehlende Werte müssen ausdrücklich kenntlich bleiben.

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

## 3. Aus Graphlinien exklusive Straßenraumflächen gewinnen (noch offen)

Die eigentliche neue Aufgabe ist die **flächentreue, überschneidungsfreie
Zuordnung** von Modul-2-Polygonen zu GIP-Abschnitten.

**Vorgesehene erste Untersuchungsmethode, noch keine festgelegte Lösung:**

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

**Bilanz-Invariante:** Summe der geometrisch vereinigten,
sich nicht überlappenden Abschnittsflächen **plus** gesonderte
Knoten- und ungeklärte Restflächen = gesamte Modul-2-Straßenraumfläche.
Die Summe der Einzelflächen darf nicht wegen gemeinsamer Kreuzungsflächen
größer werden. Ein `status` je Fläche zeigt an, ob die Zuordnung
verlässlich, randbedingt oder ungeklärt ist.

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

## Nächste konkrete Arbeit

**Als Nächstes** das neue Topologie-Audit lokal ausführen und die
Quellachsen samt Knoten in der Kartensammlung überprüfen. Vor allem die
drei kleinen separaten Netzkomponenten und die Linien im Kreuzungsbereich
müssen sichtbar beurteilt werden. Danach ein experimentelles Verfahren
zur **exklusiven Aufteilung der Straßenraum-Maske** implementieren,
einschließlich separater Knoten-/Restflächen sowie Flächenbilanz.
Bis dahin gibt es im Projekt **keine fertigen Straßenabschnittsflächen
und keine abschnittsweisen Begrünungswerte**.
