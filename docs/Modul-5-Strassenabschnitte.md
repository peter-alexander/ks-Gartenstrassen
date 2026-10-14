# Modul 5 – Straßenabschnitte als Bezugsräume

**Planungsstand: 14.10.2026. Noch keine produktiven Straßenabschnittspolygone erzeugt.**

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

## 2. Getrennter Datenbeschaffungs-Schritt (noch umzusetzen)

Für das vorhandene FMZK-Testgebiet plus begrenzten Randbereich zwei
**BBOX-begrenzte WFS-GeoJSON-Abrufe**, analog zum bestehenden
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

**Wichtiger offener Test:** Die Attribute und Topologie an den tatsächlichen
GIP-Objekten im Testausschnitt prüfen, einschließlich der Fälle mit
getrennten Richtungsfahrbahnen, Straßenbahnanlagen, Sackgassen und
mehrarmigen Kreuzungen. Allein aus der Beschreibung darf keine
lückenlose Abdeckung unterstellt werden.

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

**Zunächst den kleinräumigen GIP-Datenabruf mit strikter Geometrie-/
Attributprüfung und eine visualisierbare Achsen-/Knotenprobe umsetzen**.
Erst nach dieser Sichtkontrolle die flächige Abschnittszuordnung
programmieren und benchmarken. Bis dahin gibt es im Projekt **keine
fertigen Straßenabschnittsflächen und keine abschnittsweisen
Begrünungswerte**.
