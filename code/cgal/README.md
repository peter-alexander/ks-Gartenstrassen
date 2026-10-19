# CGAL-Prototyp für echte Segment-Voronoi-Diagramme

Diese Diagnose verändert weder die GIP-Daten noch die produktive Boost-Engine.

## Voraussetzungen in Ubuntu/WSL

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake libcgal-dev libgmp-dev libmpfr-dev
```

Das Paket `Segment_Delaunay_graph_2` gehört zum GPL-lizenzierten
CGAL-Paketbestandteil. Vor einer Verteilung oder Einbindung in das
Produktionssystem sind die Lizenzbedingungen gesondert zu prüfen.

## Erster Test

Vom Repository-Wurzelverzeichnis aus:

```bash
git pull --ff-only
bash code/scripts/run-cgal-segment-voronoi-wien.sh --timeout 30 --validate
```

Die Auswertung wird in
`output/cgal_segment_voronoi_benchmark.json` geschrieben.

Gemessen werden: fixes Segment allein, Basis allein, Kombination ohne
Rahmen, Kombination mit Rahmen sowie jeweils um 1 mm und 1 km verschobene
Kombinationen (inklusive Rahmen).

Die Millimeterkoordinaten stammen aus dem exakt gleichen genodeten
LINEAR_USE-Datensatz wie die bisherigen Boost-Diagnosen.

`--validate` prüft zusätzlich die CGAL-Datenstruktur; das ist für
einen ersten Lauf sinnvoll, kann aber zusätzliche Laufzeit benötigen.

Das Programm berechnet einen **Segment-Delaunay-Graphen**, den Dualgraphen
des gesuchten Voronoi-Diagramms. Es exportiert vorerst keine
Voronoi-Kurven, Polygone oder Zellflächen. Zahlen von CGAL und Boost sind
deshalb nicht unmittelbar als identische Topologiegrößen zu vergleichen.

## Großer Test

Erst nach erfolgreichem Kleintest:

```bash
# Nur wenn der bisherige Bericht nicht mehr unter dem Namen existiert:
# --out ist über den Python-Aufruf frei wählbar.
"$PWD/.venv/bin/python" -m scripts.benchmark_cgal_segment_voronoi \
	--cache cache/wien/linear_use.sqlite \
	--aoi cache/wien/aoi.geojson \
	--suspects output/boost_segment_voronoi_reverse_round3_minimal.geojson \
	--binary build/cgal/cgal_segment_benchmark \
	--out output/cgal_segment_voronoi_full.json \
	--timeout 120 --validate --full
```

Der große Lauf enthält alle genodeten Wiener Segmente und den Rahmen.
Jeder Fall wird in einem eigenen Prozess mit hartem Python-Timeout
ausgeführt. Der CGAL-Build selbst benötigt Zeit und ist nicht Bestandteil
des Laufzeitlimits.
