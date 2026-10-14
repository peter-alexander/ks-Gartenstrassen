# Modul 5 – Kreuzungsgrenzen aus Eck-/Übergangspunkten (Entwurf v1)

**Stand 14.10.2026: ENTWICKLUNG PAUSIERT.** Nach mehreren realen
Diagnoseläufen hat der Nutzer ausdrücklich entschieden,
**`aufteilung_v0` mit kreisförmigen Knotenbereichen (7 m)**
vorläufig beizubehalten. Die Eckpunkt-Heuristik ist
nicht fachlich validiert; keine weitere Arbeit daran,
bis ein möglicherweise früher vorhandener Kreuzungsalgorithmus
vom Nutzer gesichtet wurde. **Noch keine Kreuzungspolygone
oder neue Abschnittsaufteilung aus V1.** Der bestehende
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

## Erster lokaler V1-Diagnoselauf (14.10.2026, 13:07 UTC)

Der Nutzer hat `kreuzungen_diagnose_bericht.json` des ersten
realen Laufs mit der originalen Modul-2-Straßenmaske vorgelegt.
Die Testparameter betragen **0,75 m Profilabstand, 28 m maximale
Suchlänge und 45 m Querschnitts-Halblänge**. Der
Straßenraum-SHA-256 ist `dc53cd78d0bcd5cb242529e126a969f1be6ca5d27487ff1e85ee684654d7fc11`;
er stimmt mit den vorherigen Modul-5-Läufen überein.

**Gesamtergebnis:** 8 Kreuzungen (4 vierarmig, 4 dreiarmig),
28 Straßenarme, **828 angeforderte Querprofile, 745 gültige**
und 83 Fehler, 42 einzelne Eckpunktkandidaten sowie
**19 Schnittlinienkandidaten**. Status je Arm:
`kandidat_pruefen` 19, `uebergang_unklar` 7,
`arm_zu_kurz` 2. Es gibt **noch keine validierten Schnittlinien**
und weiterhin keine neuen Kreuzungspolygone.

| GIP-Knoten-ID | Kreuzung | Kandidaten / Arme | Fachlicher Hinweis |
| --- | --- | ---: | --- |
| `10346273` | Hahngasse / Pramergasse | 4 / 4 | alle Schnittlinien im Straßenraum |
| `10346245` | Glasergasse / Rotenlöwengasse | 4 / 4 | alle Schnittlinien im Straßenraum |
| `10346278` | Hahngasse / Seegasse / Rotenlöwengasse | 4 / 4 | Schnittlinie Achse `10040706` liegt 0,138 m außerhalb der Maske, trotzdem bisher `kandidat_pruefen` |
| `10346269` | Pramergasse / Müllnergasse | 4 / 4 | alle Schnittlinien im Straßenraum |
| `10346267` | Porzellangasse / Seegasse | 1 / 3 | ein 17,008-m-Arm zu kurz; ein Arm nur einseitig erkannt |
| `20069820` | Porzellangasse | 1 / 3 | derselbe 17,008-m-Arm zu kurz; ein Arm nur einseitig erkannt |
| `10346243` | Rotenlöwengasse / Clusiusgasse | 0 / 3 | sämtliche **83** Querprofile verworfen; zusammengefasster Fehler `mehrdeutiger_oder_ausserhalb_liegender_querschnitt` |
| `10346272` | Pramergasse / Servitengasse | 1 / 3 | zwei Arme mit nur einseitigem Übergang |

**Interpretation:**
- 16/16 mögliche Linien der vierarmigen Knoten werden als
  Kandidaten ausgegeben. Das ist ein Diagnoseergebnis und
  keine belegte Lagegenauigkeit.
- Lediglich 3/12 mögliche Linien der dreiarmigen Knoten
  werden vorgeschlagen. Die aktuelle Heuristik verlangt
  **an beiden Seiten eine nachweisbare Aufweitung**. Bei
  T-Einmündungen kann auf der durchgehenden Straßenseite
  aber ein gerader/konstanter Straßenrand existieren.
  Hier eher die unveränderte Randseite geometrisch
  nachführen und mit dem einseitig gefundenen Punkt eine
  geprüfte Querlinie bilden, **nicht** einfach eine zweite
  Aufweitung erfinden.
- Für kurze Arme zwischen nahe benachbarten Kreuzungen
  keine künstliche stabile Breitenzone erwarten. Die
  beiden Knoten **gemeinsam** prüfen und Kandidaten
  konfliktfrei auswerten.
- Bei Clusiusgasse sind `0/83` Profile gültig.
  **Nicht nachgewiesen**, ob Ursache eine außerhalb
  der Straßenraummaske liegende Achse, mehrfach geschnittene
  Querschnitte oder ein anderes Geometrieproblem ist.
  Zunächst die drei GeoJSON-Ausgaben mit der originalen
  Straßenraummaske und den Achsen überlagern und Fehler
  technisch auftrennen.
- Die 0,138 m außerhalb liegende Schnittlinie wird vom
  heutigen `outside <= 0.2`-Kriterium toleriert. In
  künftigen Versionen diesen Grenzfall **explizit
  markieren/ablehnen oder geometrisch zulässig korrigieren**;
  nicht als einwandfreie Kreuzungsgrenze verwenden.

**Nächster Schritt vor einer V1-Flächenpartition:**
Die tatsächlichen `kreuzungen_querprofile.geojson`,
`kreuzungen_eckpunkte.geojson` und
`kreuzungen_schnittlinien.geojson` räumlich prüfen.
Die eingereichte JSON-Zusammenfassung allein enthält
keine Punkt- oder Linienkoordinaten und erlaubt daher
**keine Aussage zur visuellen Lagequalität**. Danach
gezielt einseitige T-Übergänge und die Klassifizierung
ungültiger Profile nachbearbeiten. Die vorhandene
`aufteilung_v0` unverändert lassen.

## V1.1: T-Kreuzungen und alternative Gehsteigkante (14.10.2026)

Nach der ersten echten Diagnose (19 Schnittlinien bei 28 Armen)
wurden eine T-Kreuzungsregel und ein umschaltbarer Referenzrand
implementiert. Die bisherige `aufteilung_v0` bleibt unverändert;
dieses Skript erzeugt weiterhin **nur diagnostische GeoJSONs**,
keine neuen Abschnittsflächen.

### T-Kreuzung: im Zweifel rechtwinklig

Bei einem **GIP-Knoten mit Grad 3** gilt jetzt:

1. Die beiden seitlichen Übergangspunkte weiterhin getrennt aus
   den Querschnittsprofilen suchen.
2. **Nur eine Seite erkennbar:** An ihrer Entfernung `s` vom
   Knoten den **vollständigen Querschnitt senkrecht zur lokalen
   GIP-Achse** verwenden. Sein gegenüberliegender Endpunkt
   wird direkt aus dem aktiven Randpolygon ermittelt, ohne
   auf dieser Seite eine zusätzliche Aufweitung zu behaupten.
   Status/Methode `orthogonal_einseitig`.
3. **Beide Seiten erkennbar:** Den Querschnitt an der
   **weiter außen** liegenden der beiden Übergangsstationen
   verwenden. So schneidet die Linie hinter beiden Aufweitungen.
   Methode `orthogonal_beidseitig`.
4. Keine Übergangsstelle oder Schnitt durch unzulässige
   Fremdfläche: **kein erzwungener Erfolg**. Kurze Achsen,
   unklare Querprofile und die getrennten benachbarten
   Kreuzungen bleiben ausdrücklich offen.

Die exportierten Eckpunkte enthalten `methode` und
`status`. Der auf einer geraden Gegenseite nur durch
den senkrechten Querschnitt bestimmte Punkt ist als
`orthogonaler_gegenseitenpunkt_nicht_validiert` gekennzeichnet,
nicht als visuell nachgewiesener Scheitelpunkt. In den
Schnittlinien steht `methode`; keine davon ist bereits
fachlich validiert.

Bei **Grad 4** bleibt die bestehende Eckpunkt-Verbindung
als Vergleich unverändert. Eine über **0,03 m** tatsächlich
außerhalb der ausgewählten Maske verlaufende Schnittlinie
wird nun als `schnittlinie_geometrisch_abgelehnt`
markiert statt großzügig toleriert.

### Wahl der Bezugsgrenze

`--boundary-mode` bietet zwei Optionen:

| Wert | Geometrische Bedeutung |
| --- | --- |
| **`hauswand`** (Standard) | Äußere **Modul-2-Straßenraummaske**, oft entlang Hauswand/Grundstücksgrenze, nicht zwingend realer Fassadenverlauf. Gleiche Grundlage wie zuvor. |
| **`gehsteigkante`** | **Geometrische Vereinigung der FMZK-Klassen 21/30/32/33/39** (Fahrbahn, Zebrastreifen, Schwellen und Rampen, Parkspuren, sonstige Verkehrsfläche). Ihr äußerer Rand dient als **experimentelle Gehsteig-/Fahrbahnkanten-Näherung**, nicht als amtlich vermessene Bordsteinkante. |

**Erweiterung vom 14.10.2026:** Die erste reale Diagnose zeigte
bei der nur aus **F_KLASSE=21** gebildeten Alternativmaske
**15.792,00 m²**, lediglich **14 plausible von 28 möglichen
Schnittlinien** und 10 unklare Straßenarme. Mit dem äußeren
Straßenraumrand entstanden dagegen 22 plausible Schnittlinien
und 3 unklare Arme (bei jeweils 2 zu kurzen Armen und
zusätzlich 1 bzw. 2 geometrisch abgelehnten Linien).
Dieser Vergleich ist eine technische Diagnose, kein Genauigkeitsmaß.

Die alternative Maske umfasst nun **fünf offizielle FMZK-Klassen**:

| Klasse | Nutzung | Rolle |
| --- | --- | --- |
| 21 | Fahrbahn einschließlich Radwege | Basis |
| 30 | Zebrastreifen | Querschnitt nicht künstlich unterbrechen |
| 32 | Fahrbahnaufwölbung, Tempo-Schwelle, Einfahrts-/Auffahrtsrampe | Querschnitt nicht künstlich unterbrechen |
| 33 | Ruhender Verkehr im öffentlichen Gut | Park- und Abstellspuren mit einbeziehen |
| 39 | Sonstige Verkehrsfläche | Unbestimmte verkehrliche Randflächen mit einbeziehen; fachlich besonders prüfen |

**Explizit nicht einbezogen:** 22 (Verkehrsinsel,
damit echte Inseln als Aussparung erhalten bleiben), 23 (Gehsteig),
24 (Fußgängerzone), 25/26 (Verkehr auf Privatgrund) sowie
27–29 (Gleisbereiche). Diese Abgrenzung ist zunächst
ein experimenteller Querschnittsprovider, keine endgültige
Definition aller befahrbaren Flächen.

Die fünf FMZK-Flächenklassen werden geometrisch **vereinigt**
und auf die schon vorhandene Modul-2-Straßenmaske zugeschnitten.
Die Klassenflächen werden nicht einfach addiert;
der Bericht dokumentiert je Klasse **Objektzahl und
vereinigte Fläche**, zusätzlich die Fläche der Gesamtmaske.
Es gibt weder einen erneuten Datendownload noch einen
stillschweigenden Rückfall auf `hauswand`, falls eine
GIP-Achse außerhalb der vereinigten Flächen liegt.
**Modul 2 und V0 bleiben unverändert.**

Quelle zur offiziellen Klasseneinteilung:
https://www.wien.gv.at/stadtentwicklung/stadtvermessung/pdf/fmzk-attribute-wertebereiche.pdf

### Beide Varianten lokal vergleichen

```bash
git pull --ff-only

# Äußerer Straßenraum (Standard) – neues Verzeichnis, ohne den alten Lauf zu überschreiben
.venv/bin/python -m scripts.diagnose_gip_junction_corners \
  --boundary-mode hauswand \
  --out-dir data/processed/strassenabschnitte/eckpunkte_diagnose_v1_t90

# Erweiterte Verkehrsflächenmaske (Parkspuren, Schwellen etc.), neue Ausgabe
.venv/bin/python -m scripts.diagnose_gip_junction_corners \
  --boundary-mode gehsteigkante \
  --out-dir data/processed/strassenabschnitte/eckpunkte_diagnose_v1_verkehrsflaechen
```

Beide Ausgaben haben getrennte
`kreuzungen_querprofile.geojson`,
`kreuzungen_eckpunkte.geojson`,
`kreuzungen_schnittlinien.geojson` und
`kreuzungen_diagnose_bericht.json`. Der Bericht dokumentiert
`boundary_mode`, die Referenzgeometrie und deren Fläche.
Die Resultate bitte **mit denselben acht Knoten** vergleichen,
insbesondere Pramergasse/Servitengasse,
Porzellangasse/Seegasse und die Ausreißerzone an
Hahngasse/Seegasse/Rotenlöwengasse.

**Grenzen:** Die neuen T-Querlinien sind mathematisch senkrecht
zur **lokalen** GIP-Achse, jedoch noch keine bestätigten
Kreuzungsgrenzen. Eine gerundete Gehsteigkante und eine
Fahrbahnkante können deutlich verschieden sein. Die
zugrunde liegenden FMZK-Verkehrsflächen (21/30/32/33/39)
ersetzen keine separat vermessene Bordstein-Geometrie.
Insbesondere `39` ist eine breite Sammelklasse und kann
räumlich zu unerwünschten Nebenflächen führen.
Sobald eine tatsächlich erfasste Gehsteigkante verfügbar
und geprüft ist, soll sie als eigener Provider angebunden werden.

## V1.2: Beginn statt Ende der Ohrwaschln – beide Referenzen (14.10.2026)

**Rückmeldung aus der Sichtkontrolle:** Die zuvor ermittelten Punkte
lagen häufig **am äußeren Ende der Kreuzungsaufweitung**, nicht an
deren **kreuzungsnahem Beginn**. Der Algorithmus verlangte bisher
zunächst eine deutlich breitere Zone und danach drei unauffällige
Querprofile; er wählte also bewusst den ersten stabilen
*Normalquerschnitt hinter* der Aufweitung. Das war für die
gewünschte Schnittposition systematisch zu weit außen.

### Geänderte Kandidatensuche

`_side_transition(..., position="innen")` nutzt weiterhin eine
nachweisbar stabile äußere Normalbreite, sucht aber **innerhalb
der gemessenen Aufweitung** die erste gut messbare abfallende
Schulter (zunächst: 65 % des lokal festgestellten, nicht
abgeschnittenen Maximums). Abgeschnittene 45-m-Messprofile
sind nie gültige Eckpunkte. Die alte Wahl ist für den Bericht
als `position="aussen"` weiterhin verfügbar.

Kann eine innere Schulter im Kreuzzungsbereich wegen Überdeckung
durch eine kreuzende Straße nicht sauber gemessen werden,
wird der bisherige äußere Schnitt **nur mit explizitem
Status `innere_schulter_..._aussenfallback`** beibehalten.
Ein Fallback ist kein Nachweis eines inneren Punktes.

Bei T-Kreuzungen wird die **kreuzungsnähere** der zwei
inneren Stationen verwendet und der Querschnitt
rechtwinklig zur lokalen Achse gezogen. Bei vierarmigen
Kreuzungen werden die beiden inneren Seitenpunkte
verbunden. Wie zuvor muss die erzeugte Linie die aktive
Maske geometrisch korrekt durchtrennen; bei unplausiblen
Querschnitten wird sie nicht als valide ausgegeben.

### Gemeinsame Hilfsdaten für beide Varianten

Unabhängig von `--boundary-mode` wird jetzt dieselbe
**geometrisch vereinigte Verkehrsmaske F_KLASSE
21/30/32/33/39** berechnet und ausgewertet.

- **`hauswand`** (Standard): Eckpunkte und Schnittlinien
  weiterhin auf der **ursprünglichen äußeren Straßenraummaske**;
  die Verkehrsmaske liefert **zusätzliche Stationshinweise**.
- **`gehsteigkante`**: Endpunkte weiterhin auf der
  vereinigten Verkehrsflächenmaske; die äußere Maske
  liefert zusätzliche Stationshinweise.
- Eine Hilfsgeometrie darf nur eine **Station auf der
  Straßenachse**, nicht den geometrischen Endpunkt ersetzen.
  An dieser Station muss ein plausibler, vollständig
  gemessener Querschnitt **der aktiven Maske** vorliegen.
  Überbreite oder abgeschnittene Querschnitte sind keine
  bestätigten inneren Kreuzungsgrenzen.
- Zusätzlich werden die **FMZK-Gebäudekonturen Klasse 11
  (Gebäude) und 19 (Nebengebäude)** vereinigt und als
  unabhängige **Kontrollgeometrie** herangezogen. Der
  Bericht führt deren Fläche, jeder Eckpunkt den Abstand
  zur nächsten Gebäudekontur. Die Kontur wird **noch nicht
  automatisch** als neue Straßenraumgrenze verwendet;
  insbesondere Überbauungen (12) werden nicht als
  Straßenrand behandelt.

Je Arm enthält der neue Diagnosebericht
`aussenstationen_m`, `innenstationen_m`,
`verschiebung_zum_knoten_m` sowie `seitenquellen`.
Die neue GeoJSON-Schnittlinie enthält `position="innen"`;
die bestehenden Ausgabedateinamen bleiben gleich.

### Eingereichter Vergleich vor dieser Korrektur

Der lokale Bericht der **fünfklassigen Verkehrsmaske**
(13:42 UTC) zeigte eine vereinigte Bezugsfläche von
**27.562,23 m²** (Fahrbahn 21: 15.792,00 m²,
Ruhender Verkehr 33: 11.195,66 m² als Klassenflächen,
zuzüglich 30/32/39, mit möglichen Überschneidungen).
Von 28 Kreuzungsarmen lieferten lediglich **acht**
`kandidat_pruefen`, 16 `uebergang_unklar`,
zwei geometrisch abgelehnte Linien und zwei zu kurze
Arme. Die reine Klasse-21-Variante hatte 14 plausible
Linien, die äußere Maske 22. **Die neue, nun kürzer
liegende V1.2-Variante wurde noch nicht auf den echten
lokalen FMZK-Daten geprüft**; ihre Trefferzahlen und
Lagequalität bleiben offen.

### Beide neuen Diagnosevarianten ausführen

```bash
git pull --ff-only

.venv/bin/python -m scripts.diagnose_gip_junction_corners \
  --boundary-mode hauswand \
  --out-dir data/processed/strassenabschnitte/eckpunkte_v12_hauswand

.venv/bin/python -m scripts.diagnose_gip_junction_corners \
  --boundary-mode gehsteigkante \
  --out-dir data/processed/strassenabschnitte/eckpunkte_v12_gehsteigkante
```

Für einen direkten Vergleich die beiden
`kreuzungen_diagnose_bericht.json` sowie nach Möglichkeit
`kreuzungen_schnittlinien.geojson` übermitteln. Die
Sichtprüfung soll insbesondere zeigen, ob die inneren
Punkte tatsächlich **vor statt hinter den Ohrwaschln**
liegen, und ob einzelne Linien trotzdem zu weit in
die Straßenkreuzung hineingezogen werden.

**Weiterhin nicht geändert:** `aufteilung_v0`, originale
Straßenraummaske, Schnittmengen der Begrünung und
Kronenüberschirmung sowie die amtlichen GIP-Quell-GeoJSONs.

## Abschließender Vergleich der V1.2-Diagnosen (14.10.2026)

Die beiden anschließend hochgeladenen
`kreuzungen_diagnose_bericht.json`-Dateien mit identischen acht
GIP-Kreuzungsknoten wurden ausgewertet:

| Status bei 28 Armen | `gehsteigkante` | `hauswand` |
| --- | ---: | ---: |
| Schnittlinien `kandidat_pruefen` | 17 | 19 |
| `schnittlinie_geometrisch_abgelehnt` | 6 | 1 |
| `arm_zu_kurz` | 2 | 2 |
| Weitere ungeklärte / am Suchlimit endende Arme | 3 | 6 |
| Erzeugte Querprofile | 741 | 745 |
| Punktkandidaten | 46 | 40 |
| Ausgegebene Schnittlinien gesamt (auch abgelehnt) | 23 | 20 |

Die inneren Eckpunktstationen verschieben sich zwar Richtung
Kreuzungsmittelpunkt; **geometrisch verworfene Schnitte
und auffällig lange Querlinien** zeigen aber, dass die
Methode die gewünschte Topologie weiterhin nicht verlässlich
abbildet. Die Positionen der Kandidaten sind nicht
visuell als korrekt validiert. Die Flächenreferenzen
liegen bei 27.562,23 m² (vereinigte Verkehrsflächen)
beziehungsweise 46.630,56 m² (äußere Maske).
Diese Flächen sind **nur Diagnosemasken** und ändern
nicht den V0-Nenner. Die bloße Zahl der Kandidaten
ist keine Genauigkeitsmetrik.

**Beschluss:** Keine weiteren V1-/Eckpunkt-Tests als
nächster Arbeitsschritt. V0 behalten und später
mit dem eventuell vorhandenen früheren
Kreuzungsalgorithmus vergleichen. Der unten stehende
Ablauf bleibt als historische, **nicht aktive Planung**
erhalten.

## Frühere, jetzt pausierte Implementierungsplanung

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

**Aktuelle Festlegung (14.10.2026):** Eckpunkt-Diagnose
einstellen; `aufteilung_v0` mit 7-m-Kreisen als
vorläufige Arbeitsgrundlage behalten. Die bisherigen
V1-Experimente sind archivierte Vergleichsvarianten.
Keine bestehende Datei und kein Code von V0 werden geändert.
