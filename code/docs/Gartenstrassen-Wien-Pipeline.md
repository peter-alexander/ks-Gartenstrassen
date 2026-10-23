# Gartenstraßen Wien – verbindliche Produktionspipeline

Diese Datei ist der verbindliche Ablauf für den Wiener Produktionslauf.
Ältere Voronoi-, Mittelachsen-, Site-Intersection- und Preview-Dokumente
bleiben als Entwicklungsprovenienz erhalten, sind aber **keine** Alternative
zu dieser Toolchain.

## Fachlicher Vertrag

1. **Quelle:** originale GIP-`LINEAR_USE`-Geometrien und unveränderte
   originale `edge_id`, metrisch in EPSG:31256.
2. **Partition:** CGAL-Segment-Voronoi aus den genodeten Originalsegmenten.
   Zusätzlich kommen ausschließlich begrenzte native Punkt-Faces eindeutig
   innerer ursprünglicher LINEAR_USE-Stützpunkte hinzu. Endpunkte, beim Noden
   entstandene Punkte, Rahmenpunkte und mehrdeutige Stützpunkte bleiben außen
   vor.
3. **Zugehörigkeit:** Jede Face wird ausschließlich über ihren nativen
   CGAL-Generator der ursprünglichen `edge_id` zugeordnet – niemals über
   Nearest, Mittelachse, Stichprobe oder räumliche Nachbarschaft.
4. **Kreuzungen:** Die historischen `TURN_USE`-Hüllen werden vor dem
   Dissolve von jeder Face abgezogen. Bei problematischen Vereinigungen sind
   nur die dokumentierten progressiven 1–4-m-Puffer zur Auswahl derselben
   Original-Faces zulässig; die veröffentlichte Fläche wird anschließend
   immer nochmals mit dem **ungepufferten** TURN_USE abgezogen.
5. **Abschnitte:** Flächen gleicher `edge_id` werden vereinigt. Debugdaten
   dokumentieren jede nicht reguläre Behandlung; es gibt weder erfundene
   Ersatzgeometrien noch still ausgelassene `edge_id`.
6. **SIS:** Erst das Ergebnis nach TURN_USE wird mit allen SIS-Belagsflächen
   in EPSG:31256 verschnitten. Das resultierende GeoJSON in WGS84 ist die
   geometrische Quelle für Kennzahlen und Darstellung.
7. **Kennzahlen:** Bodenbegrünung ist die SIS-Vegetationsmaske `BL/ST/WI`;
   GRM2023-Baumkronen sind davon unabhängig. Ihre Schnittfläche wird einmal
   abgezogen, sodass `Boden ∪ Krone` nie doppelt zählt.

Die Prozentwerte `boden_begruent_pct`, `grm2023_baumkronen_pct` und
`vegetation_boden_oder_krone_pct` beziehen sich jeweils auf die finale
SIS-verschnittene Abschnittsfläche (0–100). Fehlende Felder blockieren
den PMTiles-Export.

## Ausführung und Fortsetzung

```bash
cd /home/openclaw/.openclaw/workspace/ks-Gartenstrassen
bash code/scripts/run-gartenstrassen-wien.sh
```

Phasen sind `prepare`, `cgal`, `stats`, `final`; mit `--from` und `--until`
kann an jeder Phase ein- oder ausgestiegen werden. Beispiel für die bereits
vorbereiteten Wiener Daten:

```bash
bash code/scripts/run-gartenstrassen-wien.sh --from stats
```

Die teuren CGAL- und GRM-Caches werden anhand ihrer jeweiligen Quellen,
Methoden und Prüfsummen geprüft. Eine vorhandene Datei ist allein nie ein
gültiger Cache-Nachweis. Alte Statistik-/Finalausgaben ohne aktuellen
Eingabe- und Implementierungsnachweis werden abgelehnt; nach fachlicher
Prüfung können sie mit `--replace-stats` bzw. `--replace-final` erneuert
werden.

## Veröffentlichte Artefakte

| Datei | Rolle |
| --- | --- |
| `output/cgal_native_faces_sis_wien.geojson` | vollständige CGAL/TURN_USE/SIS-Geometrie |
| `output/cgal_native_faces_sis_grm_wien.geojson` | vollständiges Analyse-GeoJSON mit Boden-, Kronen- und Kombinationskennzahlen |
| `output/gartenstrassen.pmtiles` | Darstellungsarchiv, Layer `gartenstrassen_wien` |
| `output/gartenstrassen_wien.metadata.json` | Quellen-/Methoden-Prüfsummen und Exportvertrag |
| `output/gartenstrassen_wien.quality.json` | vollständiger Abschluss- und Flächenbericht |
| `output/cgal_native_faces_inner_points_pre_sis_wien__dissolve_debug.geojson` | Debug vor SIS, nicht als Endprodukt verwenden |

Die PMTiles-Ausgabe nutzt Tippecanoe mit Zoom 12–14, `--full-detail=12`,\n`--low-detail=12`, `--simplify-only-low-zooms`, `--no-tiny-polygon-reduction`,\n`--no-feature-limit` und `--no-tile-size-limit`. Es werden keine Features\naufgrund von Kacheldichte absichtlich verworfen. Unterhalb Zoom 12 werden\nkeine Vektorkacheln erzeugt.\n\nDie PMTiles-Ausgabe hat eine kollisionsgeprüfte numerische `feature_id` für
Kacheln; die fachliche stabile Kennung bleibt stets die unveränderte
`edge_id`-Eigenschaft.

## Grenzen

Die Ergebnisse bilden die GIP-/SIS-/GRM2023-Stände der verwendeten Quellen
ab. Die TURN_USE-Behandlung ist eine explizite Kreuzungsflächenregel, keine
allgemeine Aussage über Eigentum. Debug- und QA-Berichte müssen bei einer
fachlichen Aktualisierung der Quellen erneut bewertet werden.
