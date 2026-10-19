# CGAL-Segment-Voronoi: SIS-Debugflächen

Die Voronoi-Verarbeitung verwendet ausschließlich **CGAL**.
Alle alten Boost-/Punkt-Voronoi-Benchmarks und Diagnoseprogramme sind entfernt.
Die bewährte Noding-Vorbereitung bleibt erhalten.

## Installation in WSL/Ubuntu

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake libcgal-dev libgmp-dev libmpfr-dev
```

## Debugflächen für ganz Wien berechnen

```bash
git pull --ff-only
bash code/scripts/run-cgal-voronoi-debug-wien.sh
```

Der Lauf konstruiert das vollständige Wiener Segment-Voronoi-Diagramm,
polygonisiert den **gesamten Wiener Begrenzungsbereich** und schneidet
die Flächen mit der realen Wien-AOI und SIS-Straßenmaske.

Es gibt keinen automatischen 500-m-Testausschnitt und keine BBOX-Option.
Die Verarbeitung kann wegen der vielen Grenzstücke, Polygonisierung und
SIS-Flächen erhebliche RAM-Ressourcen benötigen. Statusmeldungen zeigen
Kacheleinlesung, Grenzstückimport, Noding und Flächenzuweisung.

Ausgabe: `output/cgal_segment_voronoi_sis_wien.geojson` (GeoJSON
EPSG:4326, Eigentümer `edge_id`, Fläche in m²).

Eine vorhandene Ausgabe wird nicht überschrieben. Zum erneuten Ausführen
muss die alte Ausgabe ausdrücklich umbenannt oder entfernt werden.

## Ablauf

1. Verifizierte Wiener GIP-`LINEAR_USE`-Achsen laden, millimetergenau
   quantisieren und mit GEOS noding durchführen.
2. **Alle** genodeten Wiener Segmente und einen entfernten Rahmen an CGAL
   übergeben. CGAL konstruiert einen echten Segment-Delaunay-Graphen.
3. Duale Voronoi-Kanten extrahieren. Gerade Kanten, Strahlen und Linien
   werden unterschieden; CGAL linearisiert Parabelstücke für die
   Debugdarstellung.
4. Kanten an der Wiener AOI-Umgrenzung begrenzen, GIS-Polygonisierung,
   Flächen anhand des nächsten GIP-Segments einem `edge_id` zuordnen.
5. Mit der auf Herkunft und AOI geprüften SIS-Straßenmaske verschneiden.
6. Flächendeckung/Überlappung prüfen, erst danach GeoJSON atomar schreiben.

Die Voronoi-Konstruktion selbst ist **nicht** kachelweise vereinfacht.
Es wird **kein** punktbasiertes Voronoi der gesampelten Straßenachsen erzeugt.

## Noch nicht für produktive Flächenfreigabe

- Die Kurvenlinearisierung der CGAL-Ausgabe ist noch nicht unabhängig auf
  kontrollierte maximale Abweichung geprüft. Es ist eine Debug-Geometrie.
- Das vorläufige Zuweisen polygonisierter Teilflächen über einen
  Repräsentationspunkt muss mit Voronoi-Site-Identitäten und
  Mehrfachproben verifiziert werden.
- Der gesamte Stadtexport ist wegen der Geometriegröße erst nach
  erfolgreicher Fensterprüfung vorgesehen.
- Die CGAL-Segment-Delaunay-Komponente steht unter GPL-3.0-or-later
  bzw. kommerziellen Lizenzbedingungen; Verteilung/Produktiveinsatz
  benötigt eine gesonderte Lizenzprüfung.

**Keine automatische Rückkehr zu Boost und keine stillen Fallbacks.**
