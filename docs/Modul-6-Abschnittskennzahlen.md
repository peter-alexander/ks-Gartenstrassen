# Modul 6 – Kennzahlen je GIP-Straßenabschnitt

**Implementiert am 14.10.2026.** Eigenständiges Offline-Modul
**scripts/measure_sections.py**. Die erste Ausführung mit den echten
lokalen Datensätzen und die Kartenkontrolle stehen noch aus.

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
   Polygongeometrien voraussetzen.
4. **Vollständigkeit der Partition:** Vereinigung aller Abschnitte
   und ungeklärten Flächen muss dem Originalstraßenraum
   entsprechen, ohne relevante Überlappungen oder Außenanteile.
   Für die WGS84-GeoJSON-Rückprojektion gilt
   **max(0,5 m²; 0,001 % des Gesamtgebiets)** als
   offen ausgewiesene numerische Toleranz. Ein winziges
   Restpolygon unter 0,0001 m² wird ausdrücklich
   als numerischer Rest erfasst.
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

## Nächster fachlicher Schritt

Nach dem echten Lauf die einzelnen 45 Abschnitte in der
Kartensammlung prüfen und die Verteilung ihrer Grün- und
Kronenanteile vergleichen. Erst danach Kriterien
für potenzielle Gartenstraßen formulieren. Die
Kreuzungsoptimierung V1 bleibt bis auf Weiteres pausiert.
