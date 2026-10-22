# CGAL Segment-Voronoi-Exporter

```bash
sudo apt-get install -y build-essential cmake libcgal-dev libgmp-dev libmpfr-dev
bash code/scripts/run-gartenstrassen-wien.sh
```

Der native C++-Exporter gibt mit `--edges` Voronoi-Dualgrenzen
und mit `--sites` zusätzlich die tatsächlichen Generator-Sites aus.

Format `--sites`:

- `S sx1 sy1 sx2 sy2 x1 y1 x2 y2`: Segment-Site, wobei
  `s*` das ursprüngliche unterstützende CGAL-Eingabesegment bezeichnet,
  `x*` das aktuelle Segment der Site nach CGAL-Aufteilung.
- `P x y`: Punktgenerator. Wird ausschließlich gezählt,
  **nicht** zugeordnet.

Alle Koordinaten sind im lokalen CGAL-Millimeterraster relativ zum
Projektionsursprung. Die Zuordnung erfolgt über den exakten Schlüssel
des ursprünglichen Eingabesegments und die tatsächliche Segment-Site,
ohne Stichprobenpunkte oder Nearest-Heuristik.

Aktueller Export ohne SIS:
`output/cgal_original_segment_sites_pre_sis_wien.geojson`.


## Direkter nativer Face-Export

`cgal_voronoi_faces --faces OUTPUT` liest dieselben
CGAL-Eingabesegmente wie der alte Dualgrenzen-Exporter.
Anstelle der isolierten Voronoi-Grenzen werden die **Voronoi-Faces**
mit `CGAL::Voronoi_diagram_2` besucht. Der Face-Dualvertex hat die
ursprüngliche Supporting-Site, deren segmentbezogene Herkunft eindeutig
in `_noded_segments` gespeichert ist. Die CCB-Halfedges werden in
Umlaufrichtung als `H`-Records ausgegeben; darauf folgen die vom CGAL
Renderer linearisierten Kanten als `S`-Records und Trennzeichen
`E`, `Z`. `F` enthält das unterstützende Eingabesegment.

Punkt-Faces werden absichtlich **gar nicht exportiert**.
Die künstlichen Rahmen-Faces werden durch die bekannte Input-Segment-
Liste erkannt und nicht als LINEAR_USE ausgegeben. Die CCB-Geometrie
wird zu einem Polygon pro nativer Segment-Face aufgebaut, erst danach
nach `edge_id` und Zusammenhang vereinigt. Der SIS-Verschnitt folgt
noch nicht.
