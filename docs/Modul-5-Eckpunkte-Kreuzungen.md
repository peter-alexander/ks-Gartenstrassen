# Modul 5 – Kreuzungsgrenzen aus Eck-/Übergangspunkten (Entwurf v1)

**Stand: 14.10.2026. Diagnose-Prototyp implementiert; noch keine
Kreuzungspolygone und keine neue Abschnittsaufteilung.** Der bestehende
Stand `aufteilung_v0` bleibt unverändert. Der diagnostische Ansatz
aus dieser Spezifikation ist als `scripts/diagnose_gip_junction_corners.py`
implementiert und besitzt synthetische Tests. Weitere Schritte der
Spezifikation (geschlossene Kreuzungspolygone, robuste Behandlung
sämtlicher Sonderfälle und v1-Gesamtpartition) sind **noch offen**.

## Ziel: die grünen Linien der Skizze

Gesucht wird an **jedem angeschlossenen Straßenarm** einer Kreuzung
eine **Querlinie von einer Straßenseite zur anderen**. Ihre Endpunkte
liegen dort, wo die aufgeweitete bzw. gerundete Kreuzung in die
normal verlaufenden Seitenbegrenzungen des Straßenarms übergeht.
Die Schnittlinien grenzen zusammen den Kreuzungsbereich von den
eigentlichen Straßenabschnitten ab.

**Wichtig: In der idealisierten Skizze sind die Pfeilspitzen eher
*Tangenten-/Übergangspunkte* der Eckrundungen, nicht notwendigerweise
die geometrischen Scheitelpunkte oder besonders scharfe Ecken.**
Bei FMZK-Polygonen können Übergänge abgerundet, segmentiert,
unregelmäßig oder überhaupt nicht eindeutig erkennbar sein.
Auch die äußere Grenze der **heutigen Straßenraummaske** ist
nicht zwingend eine Bordsteinkante. Das Verfahren darf
deshalb keine nicht vorhandene Genauigkeit behaupten.

Eine vierarmige Kreuzung erhält im Normalfall **vier Schnittlinien**,
eine je Straßenarm; bei einer T-Kreuzung meist drei.
Das entstehende Kreuzungspolygon muss nicht exakt ein Viereck
oder Dreieck sein: Zwischen den Schnittlinien folgen die
Randstücke der tatsächlichen Straßenraumgeometrie.

## Beobachtungen aus dem realen Testausschnitt

- 80 GIP-Achsen, 47 geladene GIP-Knoten; davon **38 Knoten
  mit Grad ≥3** (**26 mit Grad 3, 12 mit Grad 4**).
- Der aktuelle v0-Lauf ordnet **43.217,91 m² auf 45 Abschnitte**
  zu; **3.368,09 m²** bleiben als `knotenbereich` (Radius 7 m),
  weitere **44,56 m²** als `sonderachse` und praktisch
  keine unzugeordnete Restfläche.
- An mindestens einer Stelle liegen zwei Kreuzungsknoten
  **nur rund 17 m auseinander**. Für diese Arme kann eine lange,
  vollständig gerade „Normalbreiten“-Zone fehlen.
- Die aus den hochgeladenen v0-Ergebnissen rekonstruierte
  Straßenraumgeometrie ist komplex (zusammenhängende
  Außenbereiche, innere Aussparungen). Für eine Implementierung
  **stets die originale** `fmzk_strassenraum.geojson` verwenden;
  die Wiedervereinigung exportierter v0-Flächen dient nicht
  als neue kanonische Straßenmaske.

## A. Eingaben und Normierung

1. Originale Modul-2-Straßenraummaske in **EPSG:31256**
   laden und geometrisch vereinigen; Eingabe-SHA-256 protokollieren.
2. GIP-Achsen, Knotengeometrien und `NODEFROM_OBJECTID`/
   `NODETO_OBJECTID` zu metrischen Graphdaten transformieren.
   Den bestehenden Topologie-Audit voraussetzen.
3. Arbeitsbereich je Knoten auf die lokale Straßengeometrie
   begrenzen; Überlappungen zwischen benachbarten
   Arbeitsbereichen ausdrücklich markieren.
4. Zunächst nur die im bestehenden v0-Verfahren als
   normale Straßen behandelten Achsen (`FOW = 3`) für
   die eigentliche Abschnittszuordnung verwenden.
   Andere Wegtypen und unklare Knoten ausdrücklich gesondert
   behandeln. Nicht automatisch FOW-3-Knoten so ausdünnen,
   dass Kreuzungsarme verloren gehen.

## B. Jeden Straßenarm orientieren

Für einen Knoten `K` alle inzidenten GIP-Achsen bestimmen.
Ihre Geometrie in Richtung **vom Knoten weg** orientieren.
Aus den ersten wenigen Metern eine robust geglättete lokale
Tangente `t(s)` und deren Normale `n(s)` berechnen.
Die Achsgeometrie muss nicht exakt mittig im Straßenraum liegen.

Die Geometrien nach Umlaufwinkel um K sortieren. Diese Reihenfolge
ist später notwendig, um Kreuzungsränder und Schnittlinien
topologisch korrekt zu verbinden. Mehrere fast parallele
Richtungsfahrbahnen, Stichverbindungen und kurze Achsen
nicht aufgrund des Winkels allein zusammenführen.

## C. Straßenquerschnitte und Übergangskandidaten finden

Für jeden Arm in kleinen Schritten `s` vom Knoten weg
Querschnitte quer zu `t(s)` bilden:

`Q(s) = centerline(s) + u * n(s)`

Den Schnitt `Q(s) ∩ Straßenraum` bestimmen und diejenige
zusammenhängende Schnittstrecke wählen, die zum betreffenden
Arm gehört und dessen Achslage enthält. Wenn die Achse außerhalb
des maskierten Straßenraums liegt oder mehrere plausible
Querschnitte vorkommen, **als mehrdeutig protokollieren**,
nicht stillschweigend den breitesten wählen.

Pro gültigem `s` erfassen:

- **L(s)**: linker Schnittpunkt mit der lokalen Straßenraumgrenze;
- **R(s)**: rechter Schnittpunkt mit der lokalen Straßenraumgrenze;
- linke/rechte Entfernung von der Achse und Gesamtbreite `w(s)`;
- Lage zu Löchern/Inseln und zusätzliche geschnittene Intervalle;
- Entfernung zum nächsten GIP-Knoten entlang der Achse.

**Anfangswerte nur zum Testen, nicht als festgelegte Parameter:**
Querschnittsschritt etwa **0,5–1 m**, Suchlänge maximal
**20–30 m**, aber durch die halbe Entfernung zum nächsten
Kreuzungsknoten begrenzt. Gerade bei nur 17 m
Knotenabstand darf kein fiktiver stabiler Arm angenommen werden.

## D. Aus der Straßenaufweitung die beiden Eckpunkte ableiten

Es geht **nicht** darum, den nächsten Vertex des FMZK-Polygons
oder das Maximum einer einzelnen Winkeländerung zu suchen.

Für jeden Arm die Folgen `L(s)`, `R(s)` und `w(s)`
in Richtung weg vom Knoten untersuchen:

1. **Normalen Armquerschnitt schätzen:** Weiter außen möglichst
   einen Abschnitt mit über mehrere Meter stabilen linken/rechten
   Begrenzungen finden. Robuste gleitende Mediane oder
   Linienanpassungen für beide Seiten verwenden.
2. **Kreuzungsaufweitung lokalisieren:** Richtung Knoten jene
   Zone suchen, in der die Querschnitte breiter werden oder
   eine Seite aufgrund der Eckrundung vom stabilen Rand
   abweicht. Auch ein nur einseitiger Übergang zählt.
3. **Seitliche Übergänge bestimmen:** `P_L` und `P_R`
   jeweils dort schätzen, wo die seitliche Abweichung bzw.
   Randkrümmung in die normale Armbegrenzung übergeht.
   Die Punkte dürfen verschieden weit vom Knoten entfernt
   sein. Bei sauber modellierten Rundungen kann
   zusätzlich die Tangentenübereinstimmung zwischen
   gerundetem Rand und geradem Arm geprüft werden.
4. **Keine eindeutige Stelle?** Wenn die Straßenmaske keine
   solche Ecke enthält, der Arm zu kurz ist oder
   der Querschnitt wegen Inseln/Gehwegen mehrdeutig bleibt,
   lautet das Ergebnis **`uebergang_unklar`**.
   Keine automatische Auffüllung durch frei geratene Ecken.

Schwellen für „stabil“ (Länge, Breitenstreuung, Richtungsänderung,
Krümmung) sind **erst nach einem visuellen Vergleich mehrerer
echter Kreuzungen** festzulegen. Eine durchgehend gleich breite
Straße und eine langgezogene Aufweitung sind verschiedene Fälle.

## E. Pro Arm eine Querlinie ableiten und geometrisch prüfen

Aus `P_L` und `P_R` entsteht die vorgeschlagene grüne
**Schnittlinie** `C = [P_L, P_R]`. Sie muss nicht zwingend
senkrecht zur GIP-Achse verlaufen.

Nur akzeptieren, wenn:

- beide Punkte innerhalb einer dokumentierten metrischen
  Toleranz tatsächlich auf den **passenden gegenüberliegenden**
  Randseiten liegen und im richtigen Umlaufsinn angeordnet sind;
- die Linie den gemeinten Straßenarm **genau einmal**
  durchtrennt, im Straßenraum liegt und nicht durch
  Inseln/Gebäude/Aussparungen oder einen fremden Arm geht;
- sie nicht eine benachbarte Kreuzung oder eine vorhandene
  Querlinie unzulässig schneidet;
- sie den Knotenbereich topologisch von der anschließenden
  Abschnittsfläche trennen kann.

Die Prüfroutine muss für jeden Versuch **beide Endpunkte,
`C`, Querschnittsprofil, Begründung und Abweichungen**
zur Verfügung stellen. Fehlerhafte Versuche werden nicht
als richtige Kreuzungsgrenzen exportiert.

## F. Kreuzungsflächen und Straßenabschnitte schneiden

Für eine Kreuzung die gültigen Querlinien **aller relevanten
Arme** zusammen mit der originalen Straßenraumgrenze
als planaren Flächengraph verwenden (`polygonize`/
`split` mit robustem Snapping an den Straßenraumrand;
kleine Schnapp-Toleranz, kein Verlust von Originalfläche).

Das **zwischen den Schnittlinien liegende Teilpolygon**
anhand der Zugehörigkeit zu Knoten und Armsystem wählen;
bei getrennten Straßenraumpolygonen oder Knoten außerhalb
der Maske geeignete mehrdeutige Kandidaten ausdrücklich
protokollieren. Die Teile auf das originale
Straßenraumpolygon begrenzen. Keine Flächen durch
Linienpuffer „aufbrauchen“; Schnittlinien selbst sind
flächenlos.

Danach auf dem Straßenraum **außerhalb** der bestätigten
Kreuzungsflächen die vorhandene exklusive
Achsen-Zuordnung aus v0 weiterverwenden, zunächst
unverändert. Sonderachsen und Restflächen bleiben
ausgewiesen.

**Fallback je Kreuzung:** Sind Übergänge nicht
bestimmbar oder die Topologie fehlerhaft, diese Kreuzung
im `knotenbereich_unklar` belassen und **nur für diesen
Fall** die bisherige Kreis-/Radius-Heuristik als
separat gekennzeichnete Prüfvariante einsetzen.
Der Radius darf nicht heimlich zur angeblich
präzisen neuen Kreuzungsgrenze werden.
Bei überlappenden Kreuzungskandidaten eine explizite
Konfliktklasse ausgeben, statt willkürlich nach
Verarbeitungsreihenfolge zu entscheiden.

## G. Ausgaben eines späteren Prototyps

Geplant (alle GeoJSON-Ausgaben EPSG:4326, Messung EPSG:31256):

- `kreuzungen_kandidaten.geojson`: vorgeschlagene neue
  Kreuzungspolygone, Kreuzungsknoten-ID, Anzahl Arme,
  Methode und Status;
- `kreuzungen_schnittlinien.geojson`: je Arm genau die
  vorgeschlagene Querlinie mit Punktpaar und Status;
- `kreuzungen_eckpunkte.geojson`: linke/rechte
  Übergangspunkte mit Quellachse und Nachweismethode;
- `abschnitte_flaechen.geojson` und
  `abschnitte_ungeklaert.geojson`: Gesamtaufteilung,
  einschließlich expliziter Fallback- und Restflächen;
- `abschnitte_bericht.json`: Vergleich v0/v1 je
  Kreuzung und für den gesamten Testbereich,
  Lücken/Überlappungen, Zuordnungsanteil,
  SHA-256 der Eingaben und Fehlergründe.

**Keine automatische Freigabe**, wenn der Anteil
„zugeordnet“ steigt: Die numerisch perfekte
Flächenbilanz aus v0 ist bereits erreicht; zu prüfen
ist die **fachliche Lage der Querlinien**.

## H. Messbare Abnahmekriterien

1. **Vollständigkeit:** Alle 38 Kreuzungsknoten haben
   einen dokumentierten Status; alle GIP-Arme eines
   Knotens sind berücksichtigt oder begründet
   ausgeschlossen. Insbesondere 26 T- und
   12 vierarmige Konstellationen.
2. **Topologie:** Eine gültige Querlinie schneidet
   den richtigen Arm einmal, ohne die Maske
   unzulässig zu verlassen. Keine
   Überschneidung zweier Kreuzungspolygone,
   keine falsche Verschmelzung naher Kreuzungen.
3. **Bilanz:** Abschnittsflächen + Kreuzungs- und
   Restflächen ergeben die exakt gleiche
   ursprüngliche Modul-2-Fläche,
   ohne doppelte Polygonflächen. Vergleich
   mit der v0-Toleranz (0,05 m²) und
   mit expliziten Fehlergrößen.
4. **Reproduzierbarkeit:** Quell-SHA-256,
   Parameter, Punkte, Linien und Status erhalten;
   erneuter Lauf erzeugt dieselben
   Geometrien und Flächen.
5. **Fachliche Stichprobe:** Normale vierarmige
   Kreuzung, T-Kreuzung, schräge Kreuzung,
   gekrümmter Gehsteigrand, Verkehrssteg,
   Platz, Insel/Loch, getrennte Fahrbahnen
   und die Kreuzungspaare mit nur
   etwa 17 m Abstand visuell prüfen.
6. **Kein Zwangserfolg:** Nicht erkennbare Ecken
   bleiben `uebergang_unklar` und erscheinen
   im Bericht; niemals schlechte Ersatzpunkte
   als bestätigte Übergänge bezeichnen.

## Erste ausführbare Diagnose (14.10.2026)

Der eigenständige Prototyp `scripts/diagnose_gip_junction_corners.py`
liest die **originale** Straßenmaske aus Modul 2 und die bereits
lokal geprüften GIP-Achsen und -Knoten. Er nutzt den vorhandenen
Topologie-Audit, prüft den Testgebietsbezug und ruft keine Webdienste ab.

```bash
git pull --ff-only
.venv/bin/python -m scripts.diagnose_gip_junction_corners
```

Standardmäßig werden **acht Kreuzungsknoten** als Stichprobe ausgewählt:
bis zu vier vierarmige und vier dreiarmige Knoten, mit Priorität
für Knoten mit vollständig aus `FOW=3` bestehenden Armen und
kurzen angrenzenden GIP-Segmenten. Alle verwendeten Knoten-IDs,
Straßennamen und Gründe stehen im Bericht. Für den direkten
Vergleich einer bestimmten Kreuzung:

```bash
.venv/bin/python -m scripts.diagnose_gip_junction_corners \
  --node-id 10346273 --node-id 10346272 \
  --out-dir data/processed/strassenabschnitte/eckpunkte_diagnose_gezielt
```

Die Standardeinstellungen messen ungefähr alle **0,75 m** einen
Querquerschnitt, suchen höchstens **28 m** vom Knoten und
höchstens bis zur halben Länge des betreffenden GIP-Abschnitts,
und verwenden höchstens **45 m Quer-Halblänge**. Sie sind
explorative Testparameter, noch keine fachlich geprüften Grenzwerte.

| Ausgabe unter `data/processed/strassenabschnitte/eckpunkte_diagnose_v1/` | Inhalt |
| --- | --- |
| `kreuzungen_querprofile.geojson` | Alle auswertbaren Querprofile pro Straßenarm: Breite, linker/rechter Abstand, Lage, Zahl zusätzlicher Teilintervalle und Kennzeichnung einer abgeschnittenen Messung |
| `kreuzungen_eckpunkte.geojson` | Vorschläge für linke/rechte Übergangspunkte, **nur Kandidaten**, mit Knoten- und Achsen-ID |
| `kreuzungen_schnittlinien.geojson` | Mögliche Verbindungsgeraden zwischen beiden Eckpunkten, mit Status `kandidat_pruefen` oder `schnittlinie_geometrisch_abgelehnt` |
| `kreuzungen_diagnose_bericht.json` | Je Knoten/Arm: Anzahl Profile, fehlende/uneindeutige Messungen, getrennter Punktstatus links/rechts, geometrischer Status der Schnittlinie, Eingabe-SHA-256 und Parameter |

**Erkennung:** Die äußerste ausreichend lange Querschnittsserie
gibt eine robuste normale Seitenbreite (Median) vor. Von der
Kreuzungsmitte weg wird eine **deutliche verbreiterte Seite**
und anschließend eine Folge von mindestens drei wieder
normalen Profilen gesucht. Nur so entstehen Kandidatenpunkte.
Ein Querprofil, das mitten in der querenden Straße die
45-m-Suchgrenze erreicht, liefert eine **abgeschnittene
Messung** und darf nicht als tatsächlicher Straßenrand
oder stabile Normalbreite missverstanden werden.

Bei einer zu kurzen Achse, unstabiler äußerer Breite,
fehlendem Aufweitungsnachweis, uneindeutigen Polygonintervallen
oder einer durch Löcher bzw. Fremdbereiche laufenden Schnittlinie
meldet die Diagnose ihre Unsicherheit. Insbesondere eine nicht
vorgeschlagene Linie bedeutet **nicht**, dass keine Kreuzung
existiert.

Die Reihenfolge bei der Kartenkontrolle: erst Querprofile
(durch Messwerte prüfen, ob überhaupt eine stabile Breite
erkennbar ist), dann Kandidatenpunkte, dann Schnittlinien
über das Orthofoto legen. Auch `kandidat_pruefen` bedeutet
**nicht validiert**.

**Es entstehen keine Kreuzungspolygone und die v0-Aufteilung
wird weder geändert noch überschrieben.** Es wird absichtlich
keine neue Zuordnungsquote ausgewiesen. Bei einer erneuten
Variante ein neues `--out-dir` verwenden.

**GitHub Actions:** Offline-Unit-Tests mit geometrisch
synthetischen Kreuzungen, einer nur gerade verlaufenden
Straßenmaske ohne Kreuzung, kurzen/Sonderachsen und der
vollständigen Nichtüberschreibung. Noch **kein** lokaler
Realtest mit der vollständigen, originalen Modul-2-Maske
bestätigt und noch keine visuelle Prüfung in Kartensammlung.

## Empfohlene Implementierungsreihenfolge

1. **Diagnose-only (Code vorhanden, lokaler Realtest offen):**
   Für acht ausgewählte echte Kreuzungen Querprofile,
   linke/rechte Kandidatenpunkte und Schnittlinien
   exportieren, **ohne** Aufteilung zu ändern.
2. **Kontrolle in Kartensammlung**: Punkte und
   Linien mit Orthofoto und Straßenraummaske
   vergleichen; Regeln dort begründet
   nachjustieren.
3. **Lokaler Kreuzungspolygon-Prototyp**:
   nur eindeutig erfolgreiche Fälle ersetzen,
   alles andere zunächst als v0/ungeklärt
   erhalten.
4. **Gesamtpartition v1**:
   mathematisch lücken-/überlappungsfrei
   validieren und räumlich mit v0 vergleichen.
5. **Erst nach fachlicher Validierung**:
   abschnittsweise Bodenbegrünung und
   Kronenüberschirmung ermitteln.

**Aktuelle Festlegung:** Den implementierten Diagnose-Prototyp
an den realen lokalen Straßenraum-/GIP-Daten ausführen und
seine vier Ausgabedateien prüfen. Kein Code von `aufteilung_v0`
oder bestehende Daten werden verändert.
