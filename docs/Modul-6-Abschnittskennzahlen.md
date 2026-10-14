# Modul 6 – Kennzahlen je GIP-Straßenabschnitt

**Implementiert am 14.10.2026.** Eigenständiges Offline-Modul
**scripts/measure_sections.py**. Der erste reale lokale Lauf
mit 45 V0-Abschnitten ist rechnerisch erfolgreich:
Originalgebiet 46.630,56 m², 0 m² fehlende Fläche,
Bodenbegrünung 889,18 m² und Kronen A/B/C
3.647,05 / 3.678,65 / 4.358,69 m².
**Die visuelle/kartografische Prüfung der 45
Einzelgeometrien bleibt ausständig.**

## Was berechnet wird

Die vorläufig maßgebliche **V0-Aufteilung bleibt unverändert**:
GIP-Voronoi, 5 m Stützpunktabstand, 25 m Achsabstand, FOW 3 und
**7-m-Kreise um Kreuzungsknoten**. Der bereits gemessene V0-Test
erbrachte 45 Abschnitte (43.217,91 m²) sowie 3.412,65 m²
Kreuzungs-, Sonderachsen- und Restflächen bei insgesamt
46.630,56 m² Straßenraum.

Für jeden Abschnitt und die separat ungeklärten Flächen:

| Kennzahl | Datenquelle |
| --- | --- |
| Straßenraum m² | V0-Teilpolygon |
| Bodenbegrünung m² und % | FMZK-Klassen 58/69 |
| Baumkronen A m² und % | Wiener Baumkataster: Kronenkreise |
| Baumkronen B m² und % | Wien und OSM: kombinierte Kronen |
| Baumkronen C m² und % | Grünraummonitoring 2023: Baumschicht |
| Vegetation D m² und % (optional) | Separat validiertes D2=0,20-Polygon-GeoJSON |

Geometrische Berechnung in **EPSG:31256**, GeoJSON-Ausgabe in
EPSG:4326. Es gibt **keine Addition** von Bodenbegrünung und
Kronenfläche und **keine Addition von A/B/C** untereinander:
A/B/C sind alternative Methoden derselben Kennzahl.

**D ist nicht automatisch verfügbar.** Die bisherigen BEV-Skripte
erzeugen noch kein eigenständiges, validiertes D2-Polygon-GeoJSON
als Standardausgabe. Ohne ein solches GeoJSON bleiben die
Vegetationsfelder leer beziehungsweise null. D2=0,20 bezeichnet
Vegetation und **nicht** bestätigte Baumkronenüberschirmung.

## Eingaben: bereits lokal vorhanden

- **data/processed/fmzk_test.gpkg** plus Manifest-JSON
- **data/processed/street_space/fmzk_strassenraum.geojson**
- **data/processed/strassenabschnitte/aufteilung_v0/** mit
  abschnitte_flaechen.geojson, abschnitte_ungeklaert.geojson
  und abschnitte_bericht.json
- **data/processed/baumkronen/baumkronen_kreise.geojson** (A)
- **data/processed/baumkronen/variante_b/baumkronen_kombiniert.geojson** (B)
- **data/processed/baumkronen/grm2023/processed/baumkronen_grm2023.geojson** (C)

Es werden **keine Netzwerkabfragen** ausgelöst. Fehlende A/B/C-
Dateien führen zu einer Fehlermeldung statt zu erfundenen
Kronenwerten. Für alternative Pfade stehen die Parameter
**--canopy-a**, **--canopy-b**, **--canopy-c**, **--fmzk**,
**--street-geojson** und **--sections-dir** zur Verfügung.

## Ersten vollständigen lokalen Testlauf starten

~~~bash
git pull --ff-only
.venv/bin/python -m scripts.measure_sections
~~~

Ausgabe in **data/processed/strassenabschnitte/kennzahlen_v0/**:

| Datei | Verwendung |
| --- | --- |
| abschnitte_kennzahlen.geojson | Abschnittspolygone mit Kennzahlen für Kartensammlung |
| ungeklaerte_kennzahlen.geojson | Kreuzungen, Sonderachsen und übrige Restflächen mit Kennzahlen |
| abschnitte_kennzahlen.csv | Alle Abschnitte **und** ungeklärten Flächen, Semikolon-CSV in UTF-8 mit BOM |
| abschnitte_kennzahlen_bericht.json | Einzelwerte, getrennte Gesamtwerte, Provenienz und Qualitätsprüfungen |

Für einen neuen Lauf ein anderes Verzeichnis mit **--out-dir**
wählen. Vorhandene Ergebnisse werden nicht überschrieben.

Die GeoJSON-Abschnittsflächen lassen sich in der Kartensammlung
beispielsweise nach **bodenbegruenung_pct**, **kronen_a_pct**,
**kronen_b_pct** oder **kronen_c_pct** einfärben. Eine Bewertung
als Gartenstraße findet noch nicht statt.

## Unverzichtbare Prüfungen

1. V0-Schema, 7-m-Knotenradius, 5-m-Punktabstand, 25-m-Achslimit
   und FOW=3 kontrollieren.
2. Die Straßenraummaske über **SHA-256** mit dem ursprünglichen
   V0-Bericht abgleichen; keine Variante mischen.
3. Eindeutige GIP-IDs, Flächen-Eigenschaften und gültige
   **metrische** Polygongeometrien voraussetzen. Die V0-Quellen
   und ihre SHA-256 müssen bei der Neuberechnung identisch sein.
4. **Vollständigkeit der Partition:** Vereinigung aller Abschnitte
   und ungeklärten Flächen muss dem Originalstraßenraum
   entsprechen, ohne relevante Überlappungen oder Außenanteile.
   **Standard: direkt metrische Neuberechnung mit maximal
   0,05 m² beziehungsweise 1 ppm** statt des fehleranfälligen
   WGS84-Importwegs. Für den optionalen Diagnosemodus
   `--partition-source geojson` galt eine deutlich gröbere
   Importtoleranz von **max(0,5 m²; 0,001 % des
   Gesamtgebiets)** – gerade die hat beim Realtest
   eine **2,201588-m²-Lücke** aufgedeckt.
   Ein numerisches Restpolygon unter 0,0001 m² wird
   gesondert nachgewiesen, nicht beliebig zugeteilt.
5. Flächenschnitte für **alle Methoden** auf jedem
   Teilpolygon ermitteln. Ein Kennzahlen-m²-Wert darf
   die Teilpolygonfläche nicht überschreiten.
6. **Gebietssummen A/B/C und Bodenbegrünung**
   müssen getrennt mit dem Schnitt gegen die
   ursprüngliche **gesamte** Straßenmaske übereinstimmen.
   Dazu zählen ausdrücklich auch die nicht zugeordneten
   Kreuzungs- und Sonderflächen. Für jede Quelle meldet
   der Bericht Abschnittsfläche, ungeklärte Fläche und
   numerische Bilanzdifferenz.
7. Bestehende Daten und V0-Geometrien bleiben unverändert.

**Plausibilitätsanker des bisherigen Testgebiets:** 889,18 m²
Bodenbegrünung sowie Baumkronen A 3.647,05 m²,
B 3.678,65 m², C 4.358,69 m². Diese Zahlen sind keine
hartcodierten Zielwerte, denn spätere konsistente neue
Datenstände müssen ebenfalls geprüft werden können.

## Korrektur des ersten lokalen Startfehlers (14.10.2026)

Ein reales V0-Abschnittspolygon (`gip:10042121`) wurde beim
Wiedereinlesen aus GeoJSON zunächst mit `gültige Polygonfläche
erwartet` abgelehnt. Die tatsächliche Ursache des einzelnen
ungültigen Rings lässt sich ohne das betreffende Original-GeoJSON
nicht abschließend zuordnen; in Betracht kommen auch
Gültigkeitsprobleme aus dem EPSG:31256/WGS84-Rundweg.

**Modul 6 prüft nun die neu projizierten Abschnittsgeometrien
und setzt nur bei Bedarf `shapely.make_valid` mit Extraktion
polygonaler Anteile ein.** Die V0-Quellgeometrie wird **nicht**
verändert. Jede tatsächlich reparierte Geometrie wird im
Feld `partition_pruefung.reparierte_geojson_geometrien`
mit GIP-ID, Fehlergrund und Flächendifferenz protokolliert.
Die anschließenden Kontrollen von Fläche je Feature,
V0-Gesamtbilanz, Lücken und Überlappungen bleiben aktiv.
Ändert eine Reparatur die Geometrie unzulässig stark oder
bleibt die Fläche leer, wird weiterhin abgebrochen.

Der Testfall mit einem selbstschneidenden Polygon und
die Zurückweisung einer inkonsistenten Quellfläche
sind durch separate Unit-Tests abgedeckt.
**Die erneute Ausführung mit den echten lokalen Daten
hat inzwischen erfolgreich stattgefunden. Die rein
metrische V0-Neuberechnung wird separat weiter verwendet.**

## Realtest-Fix: Flächenverlust bei WGS84-GeoJSON (14.10.2026)

Im ersten echten V0/Modul-6-Durchlauf waren durch den
GeoJSON-Rundweg einzelne Ringe ungültig; nach Reparatur meldete
die bisherige Flächenprüfung noch **2,201588 m² fehlenden
Straßenraum**. Dieser Wert ist eine **tatsächlich gemessene
Diskrepanz beim Import** und darf weder ignoriert noch
durch Ausweiten der Toleranz als gültig erklärt werden.
Ob ausschließlich Rundungs-/Projektionsartefakte dafür
verantwortlich sind, ist ohne Geometrievergleich nicht
abschließend bewiesen.

**Neuer Standard in Modul 6:** `--partition-source metric`.
Die bereits implementierte V0-Aufteilung wird aus der
**originalen Straßenraummaske und den ursprünglichen
lokalen GIP-Achsen/-Knoten direkt in EPSG:31256**
erneut **im Arbeitsspeicher** ausgeführt. Es werden
weiterhin exakt die **5 m / 7 m / 25 m / FOW=3**
Parameter verwendet. Das ist **keine neue V0-Variante**
und es werden keine Kreuzungsgrenzen angepasst.

Vor der Freigabe müssen die SHA-256 der Straßenraummaske
sowie der GIP-Achsen und -Knoten exakt mit dem
**bestehenden V0-Bericht** übereinstimmen. Danach werden
die gebildeten GIP-IDs, Status, Straßenname,
metrische Quellfläche jedes Abschnitts und die
V0-Gebietssummen verglichen. V0 muss erneut ohne
relevante Lücken/Überlappungen und mit derselben
Abschnittsanzahl partitionieren. Unbekannte oder
abweichende Quell-IDs, Parameter, einzelne Quellflächen
oder Hashes führen zum **Abbruch**, nicht zu einer
stillen Neuzuteilung.

Die GeoJSONs aus `aufteilung_v0` werden dabei
**nur für Quell-ID und Quellflächenverifizierung**
gelesen. Die Berechnungsgeometrie kommt aus dem
identischen metrischen V0-Algorithmus. Sie wird
**nicht aus den gerundeten GeoJSON-Koordinaten
rückprojiziert**, wodurch der bisherige
Importverlust vermieden wird.

Der Modul-6-Bericht dokumentiert im Feld
`partition_pruefung.berechnungsgrundlage` den Wert
`metrische_v0_neuberechnung` sowie die geprüften
Quellhashes und die strenge metrische Bilanz.
Die Option `--partition-source geojson` bleibt
für den alten Fehlerpfad als **Diagnose** erhalten;
sie ist nicht der Standard. Für abweichende
lokale Verzeichnisse `--gip-dir` verwenden.

**Erster neuer lokaler Testaufruf:**

~~~bash
git pull --ff-only
.venv/bin/python -m scripts.measure_sections
~~~

Die V0-Quelldateien, der GIP-Graph und die
bisherigen Berechnungsberichte bleiben
unverändert. Die neue **metrische** Methode
wurde durch Offline-Tests mit einer absichtlich
in den Exportpolygonen erzeugten Lücke,
unveränderten V0-IDs und geprüften SHA-256
abgesichert; **die reale Ausführung mit dem lokalen Original-GIP/GeoPackage
hat 45 Abschnitte mit vollständiger Flächenbilanz ergeben.**

## Nächster fachlicher Schritt

Nach dem echten Lauf die einzelnen 45 Abschnitte in der
Kartensammlung prüfen und die Verteilung ihrer Grün- und
Kronenanteile vergleichen. Erst danach Kriterien
für potenzielle Gartenstraßen formulieren. Die
Kreuzungsoptimierung V1 bleibt bis auf Weiteres pausiert.
