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

## Robuste Vertex-Konstruktion im Face-Exporter

`cgal_voronoi_faces` behält den gefilterten Double-Kernel für den
Segment-Delaunay-Graphen und dessen Topologie bei. CGAL 5.6 kann jedoch bei
zwei nahezu kollinearen Segmenten mit gemeinsamem Endpunkt und einer dritten
Punkt-Site in der gefilterten `Field_with_sqrt`-Konstruktion einen
nicht endlichen Voronoi-Vertex liefern. Die Intervallkonstruktion wirft dabei
keine Unsicherheits-Exception; CGALs normaler exakter Fallback wird deshalb
nicht erreicht.

Nur wenn diese Konstruktion tatsächlich `NaN` oder `Inf` ergibt, wird derselbe
Vertex mit `Exact_predicates_exact_constructions_kernel_with_sqrt` algebraisch
exakt neu konstruiert und anschließend einmal nach `double` konvertiert. Das
ändert weder Delaunay-Prädikate noch Topologie oder Generatoridentität. Eine
rein rationale Ring-Konstruktion ist hier nicht ausreichend: Sie erzeugt zwar
endliche, für die bekannten Fälle aber nicht äquidistante Punkte.

Vor dem Schreiben werden sämtliche Koordinaten in `F`, `P`, `H`, `S`, `R`
und `L` geprüft. Ein verbleibender ungültiger Wert bricht den Export mit Face,
Generator, Halfedge und Berechnungsstelle ab. Die JSON-Statistik enthält
`exact_vertex_fallbacks`.

Regressionstest:

```bash
cmake -S code/cgal -B build/cgal -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON
cmake --build build/cgal --parallel 2
ctest --test-dir build/cgal --output-on-failure
```

Die Fixtures unter `tests/data/nonfinite_group_{a,b}.txt` enthalten die beiden
minimalen Wiener Konstellationen einschließlich eines künstlichen Rahmens.
Der Test prüft alle Stream-Koordinaten, die betroffenen Generatoren, die
Face-Topologie sowie die Äquidistanz des gemeinsam konstruierten
Voronoi-Vertex zu beiden Segmenten und zur Punkt-Site.


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

Punkt-Faces werden exportiert und in Python ausschließlich dann übernommen,
wenn sie einem eindeutigen inneren Originalstützpunkt zugeordnet sind.
Die künstlichen Rahmen-Faces werden durch die bekannte Input-Segment-
Liste erkannt und nicht als LINEAR_USE ausgegeben. Die CCB-Geometrie
wird zu einem Polygon pro nativer Segment-Face aufgebaut, erst danach
nach `edge_id` und Zusammenhang vereinigt. Der SIS-Verschnitt folgt
noch nicht.
