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
