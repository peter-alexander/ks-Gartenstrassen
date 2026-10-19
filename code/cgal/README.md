# CGAL-Segment-Voronoi: SIS-Debugflächen

Die Voronoi-Verarbeitung verwendet ausschließlich **CGAL**.
Alle alten Boost-/Punkt-Voronoi-Benchmarks und Diagnoseprogramme sind entfernt.
Die bewährte Noding-Vorbereitung bleibt erhalten.

## Installation in WSL/Ubuntu

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake libcgal-dev libgmp-dev libmpfr-dev
```

## Debug-Ausschnitt berechnen

```bash
git pull --ff-only
bash code/scripts/run-cgal-voronoi-debug-wien.sh
```

Standardmäßig wird ein 500 m × 500 m großes Debugfenster am Schwerpunkt
der AOI verwendet und auf die AOI begrenzt.

Ein bestimmter Kartenausschnitt (EPSG:31256, Meter) wird mit `--bbox`
gewählt:

```bash
bash code/scripts/run-cgal-voronoi-debug-wien.sh \
	--bbox XMIN YMIN XMAX YMAX
```

Ausgabe: `output/cgal_segment_voronoi_sis_debug.geojson` (GeoJSON
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
4. Kanten im gewünschten Fenster begrenzen, GIS-Polygonisierung,
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
