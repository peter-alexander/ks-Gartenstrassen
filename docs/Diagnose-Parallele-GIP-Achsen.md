# Diagnose: parallele GIP-Achsen mit 20 m Suchabstand

Status: **Diagnose, keine produktive Straßenabschnitts-Vereinigung.**
Die vorhandenen GIP-Indices, Voronoi-Partitionen und Messwerte bleiben unverändert.

## Ausgangspunkt

In der [RgE-Analyse](https://github.com/peter-alexander/kartensammlung-overlay-builds/blob/main/rge-analyse/build.mjs) werden Einbahn- und Straßenachsen mit gegenseitigen Linienpuffern sowie Längenanteilen räumlich abgeglichen. Für die Radinfrastruktur werden an anderer Stelle teilweise 20-m-Puffer eingesetzt. Dieses Modul kombiniert das geometrische Prinzip mit einer Richtungsprüfung für die Gartenstraßen-GIP-Kanten. Es übernimmt **nicht** die RgE-Ergebnislogik.

## Kandidatenerkennung

- **Suchabstand: 20 m**, gemessen zwischen metrischen Achslinien in EPSG:31256. Ein 20-m-Puffer um jede Linie entscheidet, wie viel Länge der jeweils anderen Linie in ihrer Nähe liegt. Die 20 m sind **kein** Maximalabstand an jedem Punkt; kürzere nicht überdeckte Teilstücke können weiter auseinanderliegen.
- **Längenüberdeckung:** Mindestens **85 % der kürzeren** und **60 % der längeren** Achse liegen im jeweiligen Gegenpuffer. Diese symmetrische Rollenzuordnung ersetzt die festen Rollen „Einbahn“/„Straße“ der RgE-Analyse.
- **Verlaufsrichtung:** Zusätzlich werden alle 5 m lokale Tangenten mit bis zu 25° Abweichung verglichen; gegenläufig digitalisierte Linien sind erlaubt. Auch beim richtungskonformen Anteil sind 85 % der kürzeren und 60 % der längeren Linie gefordert.
- **Räumliche Vorauswahl:** Shapely STRtree mit 20-m-Abstandsbedingung. Jede Kombination wird einmal untersucht. Eine bloße Kreuzung oder ein gemeinsamer Endknoten reicht nicht.
- **FOW-Positivliste:** Nur Fahrbahnen (2, 3), Fußgängerzonen (14) und begleitende Fuß-/Radwege (15, 504, 505) werden untersucht. Ein Kantenpaar benötigt mindestens eine Straßenachse (2, 3, 14). Alle anderen FOW-Typen, auch Bahn, Kreuzung, Objektwege, unbekannte Codes, werden **bereits vor dem Vergleich ausgeschlossen**. Namen und gemeinsame GIP-Knoten bleiben Prüfinformationen. Details: [GIP-FOW-Auswahl](GIP-FOW-Auswahl.md).

**Wichtig:** Das ist eine bewusst großzügige Kandidatensuche. Benachbarte, eigenständige Straßen können trotz Nähe und gleicher Richtung Treffer sein. Darüber hinaus können verkettete Paare transitive Gruppen bilden, obwohl ihre äußersten Kanten nicht zueinander passen. Solche Gruppen sind **keine automatisch freigegebenen Straßenabschnitte**. Für die eigentliche Zusammenfassung braucht es eine Prüfung von Namen, Graphverbindungen, Kreuzungen, FOW, Mehrfachzuordnungen und räumlicher Topologie.

## Ausführen – ausschließlich Wien gesamt

Nach dem lokalen Umzug nach `data/wien`:

~~~bash
bash scripts/run-gip-parallel-wien.sh
~~~

Der Einstiegspunkt verwendet immer `data/wien/analysis/wien/gip.sqlite` und
`raster.json` (oder den explizit angegebenen `SIS_WIEN_ROOT`).
Vor der Berechnung werden die echte Wien-AOI über das Rastermanifest geprüft
(350–500 km², mindestens 400 Rasterkacheln), die Manifest-SHA im GIP-Index
abgeglichen und mindestens 10.000 GIP-Achsen sowie die Index-Metadaten verlangt.
Eine Testkachel oder ein Alsergrund-Pilot wird damit abgewiesen.

Direktaufrufe von `scripts.diagnose_parallel_gip` benötigen nun verpflichtend
`--manifest` zusätzlich zu `--gip-index` und `--out-dir`.
Die 20 m bleiben über `--distance-m` konfigurierbar.
Bereits vorhandene Diagnoseausgaben werden nicht überschrieben.

Den Umzug von `~/Gartenstrassen` in das lokale Repository beschreibt
[Wien-Datenumzug](Wien-Datenumzug.md).

Ausgaben:

- `parallelpaare.json`: Parameter, Zahl räumlicher Kandidaten und akzeptierter Paare, beidseitige Deckungsgrade/Richtungsanteile, FOW, Namensgleichheit, gemeinsame Knoten und verbundene Kandidatengruppen.
- `parallelpaare.geojson`: die ursprünglichen Achsen beider Seiten jedes akzeptierten Paares, mit Paar- und Gruppenkennungen, um sie direkt in einem GIS oder im Kartenwerkzeug zu prüfen (EPSG:4326).

Für die fachliche Prüfung zuerst getrennte Fahrbahn-/Radwegpaare, parallele benachbarte Straßen, Brücken/Unterführungen, Kreuzungsnähe und Gruppen mit mehr als zwei Achsen betrachten. Erst nach dieser Prüfung über die Gruppierung **der exklusiven Straßenflächen** entscheiden; GIP-Quellkanten und IDs nicht destruktiv verschmelzen.

Offline-Tests:

~~~bash
.venv/bin/python -m unittest tests.test_diagnose_parallel_gip -v
~~~
