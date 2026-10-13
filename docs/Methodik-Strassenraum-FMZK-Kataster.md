# Methodik und Arbeitsstand: FMZK-Straßenraumabgrenzung

**Stand:** 13. Oktober 2026 · **Status:** funktionierender, visuell plausibler **Zwischenstand**; **keine endgültige, flächendeckend validierte Lösung**.

> **Entscheidung:** Die vorläufige Abgrenzung wird als Arbeitsgrundlage für den nächsten Analyseschritt verwendet. Weitere Präzisierungen bleiben ausdrücklich möglich. Eine gute Darstellung im Testgebiet ersetzt keine systematische Qualitätsprüfung für ganz Wien.

## Ziel und Einordnung

Für die datenbasierte Suche nach bestehenden Wiener „Gartenstraßen“ müssen Flächen im Straßenraum von Gebäudegrundstücken, Innenhöfen, Privatgärten und anderen Flächen getrennt werden. Die Flächenmehrzweckkarte (FMZK) liefert dafür detaillierte Flächentypen, aber **keine vollständige, eindeutig als öffentlicher Straßenraum ausgewiesene Grenze**.

Die derzeitige Lösung verbindet die **FMZK-Geometrie und -Klassifikation** mit dem **Grundstücks-Layer `gst`** und den **Nutzungsflächen `nfl`** aus den BEV-Kataster-Vektorkacheln. Dadurch lassen sich Straßenraum und straßenbegleitende Flächen oft besser einordnen als durch bloße Nähe zu Gehsteigen und Fahrbahnen.

Das Ergebnis ist eine **GIS-Arbeitshypothese zur tatsächlichen Straßennutzung**, **keine** Feststellung der straßenrechtlichen Widmung, Eigentumsverhältnisse oder öffentlichen Zugänglichkeit. „Übrige Flächen“ sind insbesondere **nicht automatisch privat** und **nicht automatisch ausgeschlossen**, irgendwann als Straßenraum bestätigt zu werden.

## Datenstand und reproduzierbarer Testausschnitt

| Datensatz | Quelle / Rolle |
| --- | --- |
| Original-FMZK | `FMZK_WIEN_GP.gpkg`, Layer `FMZK_WIEN_20260112`; 2.700.160 Objekte, EPSG:31256; lokal |
| FMZK-Testausschnitt | `data/processed/fmzk_test.gpkg`, Layer `fmzk`; **2.401 Flächen** aller Klassen; auf Testgebiet zugeschnitten |
| FMZK-Extraktionsbericht | `data/processed/fmzk_test.json`; Quelle, BBOX, CRS, Verarbeitung |
| BEV-Grundstücke | Vektorkacheln `https://kataster.bev.gv.at/tiles/kataster/{z}/{x}/{y}.pbf`, Quelllayer `gst` |
| BEV-Nutzungsflächen | Dieselben Vektorkacheln, Quelllayer `nfl` mit `ns` (Nutzungscode) |
| Grundstücksdetails (optional) | `https://kataster.bev.gv.at/api/gst/<kgez>/<gnr>/` mit Nutzungsbilanz des gesamten Grundstücks; im Oktober 2026 vorübergehend gestört |

**Test-BBOX (EPSG:4326):** `16.361012,48.221226,16.366948,48.224902`; darunter der Bereich **Seegasse / Pramergasse / Müllnergasse / Porzellangasse** im 9. Wiener Gemeindebezirk. Für den Kataster wurden **16 Kacheln auf Zoomstufe 16** verarbeitet.

Alle Geometrievergleiche erfolgen in **EPSG:31256** (metrische Flächenberechnung); GeoJSON wird in **EPSG:4326** ausgegeben. Der FMZK-Ausschnitt ist bereits durch die Extraktion begrenzt. Die Katasternutzungen beziehen sich ebenfalls nur auf den verfügbaren Ausschnitt und ggf. darüber hinaus geladene Tile-Fragmente – **nicht auf vollständige Grundstücke**.

## Verarbeitungsschritte und verbindlicher Stand des Codes

### 1. FMZK-Kern ermitteln

Als klar identifizierbarer **Straßenraum-Kern** gelten momentan:

| `F_KLASSE` | Beschreibung |
| --- | --- |
| 21 | Fahrbahn |
| 23 | Gehsteig |
| 24 | Fußgängerzone |
| 33 | Ruhender Verkehr |
| 39 | Sonstige Verkehrsfläche |

Die Klassen **58/69** (Grün) und **59** (andere befestigte Flächen) sind **nicht allein aufgrund ihrer FMZK-Klasse** dem Straßenraum zugeordnet. Die bereits untersuchten Kontakte zum Kern – Nähe, Nachbarschaft, mehrseitige Einbettung – bleiben wertvolle **Prüfindizien**, begründen derzeit aber keine positive automatische Zuordnung.

Referenz: `scripts/analyze_street_space.py`.

### 2. Über den FMZK-Kern betroffene Grundstücke ermitteln

Der Kern wird mit den `gst`-Polygonen geschnitten. Identität eines Grundstücks ist **`(kgez, gnr)`**, also Katastralgemeinde und Grundstücksnummer; Kachelfragmente mit gleicher Kennung werden zusammengeführt.

Die aktuelle Katasteranalyse nimmt **jede positive Flächenüberschneidung** auf, auch unter 1 m². Das ist für die Suche vollständig, erfordert aber bei der Auswertung Aufmerksamkeit: Viele minimale Schnitte sind wahrscheinlich nur Geometrie- oder Lageabweichungen an Grundstücksgrenzen. **„Vom Kern berührt“ bedeutet noch nicht „Straßengrundstück“.**

Referenz: `scripts/analyze_kataster.py`.

### 3. `nfl`-Nutzungen räumlich vergleichen

Für die durch den Kern gefundenen Grundstücksausschnitte werden die vorhandenen `nfl`-Flächen herangezogen.

- `ns=95`: **Straßenverkehrsanlagen**; starkes Indiz für den Straßenraum.
- `ns=65`: **Verkehrsrandflächen**; ebenfalls straßenraumbezogen.
- `ns=42`: **Parkplätze**; verkehrsbezogen, aber **nicht automatisch** als allgemeiner Straßenraum ausgewiesen.
- `ns=41` / `52` / `83`: unter anderem **Gebäude**, **Gärten** und **Gebäudenebenflächen**; keine automatische positive Straßenraumzuordnung.
- Weitere bekannte Codes werden als sonstige Nutzung behandelt; unbekannte Codes dürfen nicht stillschweigend als Verkehr gelten.

Die Vektorkacheln können Nutzungsflächen **an Tilegrenzen fragmentieren** und **Fragmente mehrfach enthalten**. Der Export bildet deshalb eine **geometrisch vereinigte Straßenmaske (95/65)** und eine **geometrisch vereinigte Maske übriger Nutzungen**, statt Stückflächen einfach zu addieren. Ungültige Polygonringe werden vor dem Vergleich mit `make_valid` repariert, sofern möglich; fehlerhafte oder inkonsistente Eingaben dürfen die Auswertung abbrechen.

**Wichtig:** Die Masken entstehen ausschließlich aus den `nfl`-Flächen **auf den zuvor über den FMZK-Kern identifizierten Grundstücken**. Das bedeutet: Straßenraum **ohne** Bezug zu einer der Kernflächen kann übersehen werden. Die Masken sind keine vollständige Kataster-Flächenbilanz eines Grundstücks.

### 4. Jedes originale FMZK-Polygon genau einmal zuordnen

Der aktuelle Export `scripts/export_fmzk_strassenraum.py` hält die **originale FMZK-Polygonabgrenzung** bei der Klassifikation bei; es wird **nicht an einer Katastergrenze zerschnitten**.

Die aktuell implementierten Regeln, in dieser Reihenfolge:

1. **Kernklassen 21/23/24/33/39 → `strassenraum`**, unabhängig von einem möglichen Katasterkonflikt. Bei deutlicher Abweichung wird `pruefhinweis=kern_abweichung_zum_kataster` gesetzt (weniger als 90 % Straßenmasken-Deckung oder mehr als 10 % andere Nutzungen).
2. **Alle weiteren FMZK-Klassen → `strassenraum`**, wenn das gesamte FMZK-Polygon zu **mindestens 95 %** auf der vereinigten `nfl`-Straßenmaske **95/65** liegt **und höchstens 5 %** von anderen `nfl`-Nutzungen getroffen werden. Zuweisungsgrund: `nfl_95_65_hohe_deckung`.
3. **Alle übrigen FMZK-Polygone → `uebrige`**. Mit `teilweise_strassenlage_pruefen`, wenn es einen noch so kleinen Schnitt mit 95/65 gibt; alternativ Hinweis auf fehlende Katasterabdeckung oder `keine_strassenlage_nachgewiesen`.

**Wichtig bei Schritt 3:** Die zweite Datei enthält neben eindeutig anders genutzten Flächen **auch noch nicht zugeordnete Straßenraumkandidaten**; `uebrige` ist eine konservative Restklasse, keine endgültige Negativentscheidung.

Die **95-%-Grenze ist eine Arbeitsschwelle**, kein aus unabhängigen Referenzdaten optimierter Wert. Sie ist über `--min-strassenanteil` nur für Vergleichstests veränderbar.

### 5. Zwei Ausgaben erzeugen

Lokale Outputs unter `data/processed/street_space/`:

| Datei | Inhalt |
| --- | --- |
| `fmzk_strassenraum.geojson` | Vorläufig als Straßenraum identifizierte **ganze FMZK-Polygone** |
| `fmzk_uebrige_flaechen.geojson` | Alle anderen FMZK-Polygone, einschließlich Prüffälle |
| `fmzk_aufteilung_bericht.json` | Objektzahlen, Flächensummen, Regeln und Zuweisungsgründe |

Die Attribute enthalten `fid`, `f_klasse`, `f_klasse_text`, `zuordnung`, `grund`, `flaeche_m2`, die Kataster-Flächenanteile `kataster_strassenanteil_pct`, `kataster_sonstige_pct`, `kataster_ohne_nutzung_pct` und ggf. `pruefhinweis`; wo verfügbar auch `fmzk_id` und weitere Quellattribute.

**Soll-Invariante:** Beide GeoJSONs zusammen enthalten **jedes Objekt des ursprünglichen Test-GeoPackages einmal**, ohne wegen der Zuordnung Geometriefragmente hinzuzufügen oder auszuscheiden. Diese Invariante wird im Export bzw. in Tests geprüft; der genaue lokale Real-Daten-Export kann zusätzlich über den Bericht kontrolliert werden.

## Ergebnisse der ersten Katasterprüfung (Testgebiet, 13.10.2026)

**Gesichert aus `kataster_grundstuecke.csv` und `kataster_bericht.json`:**

- **2.547 Grundstücks-IDs** wurden in den 16 Kacheln gesehen.
- Der FMZK-Kern hat **190 Grundstücksausschnitte** mit positiver Flächenüberschneidung.
- Die exportierte Nutzungs-Geometrie umfasst **507 `nfl`-Fragmente**, teils durch Kachelgrenzen gedoppelt.
- Nutzungsgruppen der 190 Kern-getroffenen Grundstücke **innerhalb des untersuchten Ausschnitts**:

| Beobachtung aus `nfl` im Ausschnitt | Grundstücke | Summe der Kern-Überschneidungen* |
| --- | ---: | ---: |
| Nur `95`/`65` | 25 | 37.581,13 m² |
| `95`/`65` **und** andere Nutzung | 3 | 6.246,12 m² |
| Kein `95`/`65` | 162 | 495,09 m² |
| **Insgesamt** | **190** | **44.322,34 m²** |

\* **Nicht** die Flächen der Katastergrundstücke; dies sind aufsummierte FMZK-Kernüberschneidungen je Grundstück. Wegen sehr kleiner Überlagerungen und Rundung ist die Summe **kein geometrisch vereinigter Flächennachweis** und geringfügig größer als die eigentliche Kernfläche. **98,88 %** dieser summierten Überschneidungen liegen auf den 28 Grundstücken mit Nutzungs-Code 95/65 im Ausschnitt.

Das sind **keine 98,88 % Klassifikationsgenauigkeit**, sondern lediglich eine **räumliche Übereinstimmung zweier Datenquellen für den bereits festgelegten Kern**. Im beobachteten Ausschnitt war **kein `ns=65`** unter den Kern-getroffenen Grundstücken; die entsprechende Straßen-Nutzung war `95`.

Die **162 Grundstücke ohne 95/65** umfassen zahlreiche minimale Grenztreffer. Ein größerer Sonderfall ist **KG 01002, Grundstück 1105/1**: Nutzung `42` (Parkplätze), **279,19 m²** Überlappung zum FMZK-Kern. Dieser Fall ist **nicht** automatisch als sonstiger Raum wegzuinterpretieren – er bleibt fachlich prüfenswert. Weitere Grenzfälle sind **KG 01002/1274** und gemischt genutzte Grundstücke wie **01002/1517** und **01002/1252/12**.

Die BEV-Detail-API war zeitweise nicht erreichbar. Deshalb gab es zur ersten Auswertung **keine neuen Grundstücks-API-Abfragen**; **drei** ganze Nutzungsbilanzen waren aus früherem Cache verfügbar (**Klasse C: 3**), **187** waren mangels API-Details **Klasse D**. Die Klassen A/B/C/D für **gesamte Grundstücke** sind strikt von den oben dargestellten **`nfl`-Beobachtungen im Testausschnitt** zu unterscheiden. A/B=0 ist bei dieser Cachelage **kein Gegenbeweis** für die Methode.

## Sichtprüfung der ersten beiden Exporte

Am **13.10.2026** wurden beide GeoJSONs gemeinsam mit einem Stadtplan/Kataster visuell geprüft.

- **Übersicht:** Die als Straßenraum gekennzeichneten FMZK-Flächen bilden weitgehend die zusammenhängenden Straßenkorridore zwischen den Häuserblöcken ab, während überwiegend blockinnere bzw. bebaute Bereiche in der zweiten Ausgabe landen.
- **Detailansicht Seegasse:** Das Resultat folgt dem Straßenraum überwiegend überzeugend. Entlang der Grundstücks- und Gebäudegrenzen sind kleine Versätze, Vorsprünge und uneindeutige Grenzstücke zu sehen. Diese lassen sich aus den beiden Bildern nicht sämtlich verifizieren.
- **Rückmeldung:** „Nicht hundertprozentig, aber schon sehr sehr gut.“ Damit ist die Methodik für einen **explorativen nächsten Schritt** brauchbar, nicht abschließend validiert.

Die Bildschirmbilder dienen als **qualitative Plausibilitätsprüfung**; aus ihnen kann weder eine Fehlerrate noch Vollständigkeit oder rechtliche Straßenraumzugehörigkeit abgeleitet werden. Die Screenshots sind zurzeit **nicht Bestandteil dieses Repos**; diese Dokumentation hält die zugehörigen Beobachtungen fest.

## Bekannte Grenzen und mögliche Verfeinerungen

1. **Öffentlicher Raum vs. Kataster-Nutzung:** `nfl.ns` beschreibt eine Nutzung, **keine Eigentümerschaft oder Widmung**. Das betrifft auch private Straßen, Parkplätze, Höfe und öffentlich zugängliche, aber anders gewidmete Grundstücksteile.
2. **Sehr kleine Grenzversätze:** Eine reine positive Flächenüberschneidung mit dem Kern führt zu vielen trivialen Grundstückstreffern. Für spätere Priorisierung können absolute Fläche, Flächenanteil und ggf. ortsabhängige Toleranzen herangezogen werden; **noch nicht** automatisch wegfiltern.
3. **Kleinräumige Grünflächen/Baumscheiben:** Wegen Tile-Geometrie, ungeeigneter Nutzungsgrenzen oder knapper 95-%-Schwelle können echte Straßenraumflächen konservativ in `uebrige` verbleiben. Das ist besonders für spätere Begrünungskennzahlen kritisch.
4. **Größere gemischte Grundstücke:** Ein Grundstück kann zum Großteil Straße sein und kleine Gebäude-/Nebenflächen enthalten. Der aktuelle Export trifft **Entscheidungen pro FMZK-Polygon**, nicht pro vollständigem Grundstück; dies ist bewusst, kann aber einzelne schwierige Fälle nicht trennen.
5. **Nur vom Kern abgeleitete Katasterauswahl:** Zusätzliche Straßenflächen **ohne** jeden Kernkontakt sind derzeit keine eigenständige Suchquelle. Ein späterer Ergänzungslauf könnte `nfl`-95/65-Flächen unabhängig vom Kern prüfen.
6. **Polygonweise binäre Entscheidung:** Die FMZK-Polygone werden nicht geteilt. Ein einzelnes Objekt mit sowohl straßenseitiger als auch privater Teilfläche muss als Ganzes zugeordnet werden – potenzielle Fehlentscheidung an der Grenze.
7. **Kachelgeometrie:** BEV-Vector-Tiles sind für Darstellung bestimmt und können geschnitten, vereinfacht oder überlappend sein. Die aktuelle Vereinigungs-/Reparaturlogik verhindert die gröbsten Doppelzählungen, macht die Geometrie aber nicht zu rechtsverbindlichen Grundstücksgrenzen.
8. **Schwellenparameter:** Die 95-%-Regel sowie die Kernkonflikt-Schwellen 90/10 % sind noch **nicht systematisch kalibriert**. Änderungen erst anhand **konkreter FIDs und verifizierter Fehlerbilder** vergleichen.
9. **Testgebiet und Stichproben:** Der Blick auf einen einzigen Wiener Ausschnitt ist keine Aussage für ganz Wien. Eine frühere **gezielt geschichtete** manuelle Stichprobe von 25 FMZK-Kandidaten ergab **14 Straßenraum / 4 nicht Straßenraum / 7 unklar**; sie war **nicht zufällig** und validiert **nicht automatisch** den hier beschriebenen neuen Export.
10. **Betriebs- und Datenstand:** Die Grundstücks-API wird standardmäßig nicht aufgerufen. Die Flächenoutputs basieren auf lokal gespeicherten Testdaten. Die resultierenden Dateien sind **nicht versioniert**, nur Code und Methodik. Nach Änderungen an Extraktion, Cache oder Klassifikationsregeln Vergleichsläufe samt Bericht aufbewahren.

## Reproduzieren, ohne die Grunddaten zu verändern

Voraussetzung: bereits vorhandene lokale FMZK-Extraktion und die Kataster-Ausgaben aus Schritt 5 im selben Testgebiet. Für einen reinen Neu-Export sind **keine Netzwerk- oder Grundstücks-API-Abfragen** erforderlich.


```bash
.venv/bin/python -m scripts.export_fmzk_strassenraum
```

Die vorläufige Vorstufenanalyse kann bei Bedarf wiederholt werden:


```bash
.venv/bin/python -m scripts.analyze_street_space
.venv/bin/python -m scripts.analyze_kataster
```

**Kontrolle nach jedem Export:** `fmzk_aufteilung_bericht.json` auf Objektzahlen und `entscheidungen` prüfen, beide GeoJSONs zusammen mit Grundstücksgrenzen in der Kartensammlung öffnen und besonders FIDs mit `grund=teilweise_strassenlage_pruefen` sowie `pruefhinweis` ansehen. Nicht automatisch eine hohe Pixel-/Flächenübereinstimmung mit Ground Truth verwechseln.

Die Implementierung ist über vier Kernskripte nachvollziehbar: `scripts/extract_fmzk.py`, `scripts/analyze_street_space.py`, `scripts/analyze_kataster.py`, `scripts/export_fmzk_strassenraum.py`; dazu die zugehörigen Tests unter `tests/`.

## Entscheidung für die nächste Projektphase

**Vorläufig eingefrorene Basis:** Die bestehende FMZK-Kataster-Aufteilung bleibt zunächst **unverändert**. Ein neuer Arbeitsabschnitt darf ihre `fmzk_strassenraum.geojson` als **vorläufige Bezugsfläche** nutzen, muss den Unsicherheitsstatus weiterhin mitführen und sollte aus `fmzk_uebrige_flaechen.geojson` offen gebliebene Kandidaten nicht als gesicherte Nicht-Straßenraumflächen interpretieren.

**Sinnvoller nächster fachlicher Schritt:** Die *Bodenbegrünung* innerhalb der vorläufig identifizierten Straßenraum-FMZK-Objekte **als eigenständige, reproduzierbare Kennzahl** bestimmen (zunächst für den Testausschnitt), **noch ohne Kronenüberschirmung** und noch ohne Anspruch auf eine endgültige Gartenstraßenklassifikation. Danach die räumliche Zuordnung zu einzelnen Straßenabschnitten vorbereiten. Begrünte Flächen und Baumkronen dürfen in späteren Kennzahlen nicht unbemerkt doppelt gezählt werden.

**Verfeinerungsauslöser:** Erst gezielte visuelle Gegenbeispiele mit FMZK-`fid`/ `fmzk_id`, Kataster-`(kgez,gnr)`, Nutzungscodes, Fehlertyp und gewünschtem Ergebnis sammeln. Dann jeweils *eine* Regel ändern und denselben Referenzausschnitt erneut vollständig auswerten. Das erhält Vergleichbarkeit und verhindert rückwirkend kaum nachvollziehbare Änderungen.

---

**Diese Datei dokumentiert ausdrücklich eine Zwischenmethode (Stand 13.10.2026), keine endgültige Lösung.**
