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
- **Attribute:** Straßenname, FOW und gemeinsame GIP-Knoten werden als Prüfinformation erfasst, **nicht** als unbedingte Ausschlusskriterien. Damit werden auch potenzielle Fahrbahn–Radweg-Paare sichtbar.

**Wichtig:** Das ist eine bewusst großzügige Kandidatensuche. Benachbarte, eigenständige Straßen können trotz Nähe und gleicher Richtung Treffer sein. Darüber hinaus können verkettete Paare transitive Gruppen bilden, obwohl ihre äußersten Kanten nicht zueinander passen. Solche Gruppen sind **keine automatisch freigegebenen Straßenabschnitte**. Für die eigentliche Zusammenfassung braucht es eine Prüfung von Namen, Graphverbindungen, Kreuzungen, FOW, Mehrfachzuordnungen und räumlicher Topologie.

## Ausführen

Mit vorhandenem SIS/GIP2-Index:

~~~bash
.venv/bin/python -m scripts.diagnose_parallel_gip \
	--gip-index data/processed/sis-v2-run/gip.sqlite \
	--out-dir data/processed/sis-v2-run/gip-parallel-20m
~~~

Oder auf dem wienweiten GIP-WFS-Index:

~~~bash
.venv/bin/python -m scripts.diagnose_parallel_gip \
	--gip-index data/processed/wienweit/wien/gip.sqlite \
	--out-dir data/processed/wienweit/wien/gip-parallel-20m
~~~

Der Parameter `--distance-m` ist optional (Standard: `20`). Die Ziele müssen neu sein oder noch keine der Diagnoseausgaben enthalten. Das Skript überschreibt keine vorhandenen Berichte.

Ausgaben:

- `parallelpaare.json`: Parameter, Zahl räumlicher Kandidaten und akzeptierter Paare, beidseitige Deckungsgrade/Richtungsanteile, FOW, Namensgleichheit, gemeinsame Knoten und verbundene Kandidatengruppen.
- `parallelpaare.geojson`: die ursprünglichen Achsen beider Seiten jedes akzeptierten Paares, mit Paar- und Gruppenkennungen, um sie direkt in einem GIS oder im Kartenwerkzeug zu prüfen (EPSG:4326).

Für die fachliche Prüfung zuerst getrennte Fahrbahn-/Radwegpaare, parallele benachbarte Straßen, Brücken/Unterführungen, Kreuzungsnähe und Gruppen mit mehr als zwei Achsen betrachten. Erst nach dieser Prüfung über die Gruppierung **der exklusiven Straßenflächen** entscheiden; GIP-Quellkanten und IDs nicht destruktiv verschmelzen.

Offline-Tests:

~~~bash
.venv/bin/python -m unittest tests.test_diagnose_parallel_gip -v
~~~
