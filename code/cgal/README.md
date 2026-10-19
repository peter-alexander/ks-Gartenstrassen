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

## Vollständiger Wien-Lauf nach erfolgreichem Kleintest

Der separate Starter verwendet das bereits kompilierte CGAL-Binary,
führt **nur** die vollständigen Wiener Fälle aus und überschreibt den
Kleintestbericht nicht:

```bash
git pull --ff-only
bash code/scripts/run-cgal-segment-voronoi-full-wien.sh
```

Ergebnisse: `output/cgal_segment_voronoi_full.json`.

Vier Fälle werden auf dem gleichen genodeten Gesamtbestand getestet:

- Ohne Rahmen
- Mit unverändertem Rahmen
- Mit Rahmen und +1 mm Verschiebung von Achsen und Rahmen
- Mit Rahmen und +1 km Verschiebung von Achsen und Rahmen

Jeder Fall erhält 300 Sekunden Timeout; der Bericht wird nach jedem
Fall gespeichert. Der Starter verweigert ein versehentliches
Überschreiben einer vorhandenen Ergebnisdatei. Die
Graph-Gültigkeitsprüfung (`--validate`) ist aktiviert.

Der Bericht vergleicht die Anzahl von Eingabe-Sites, Ausgabe-Sites,
Vertices und Faces gegen den unverschobenen Wien-Fall. Gleiche Anzahlen
sind eine notwendige, **aber keine hinreichende** Bedingung für
geometrische Gleichheit. Die vollständige Rekonstruktion der dualen
Voronoi-Kanten, inklusive gekrümmter und unendlicher Grenzen, und der
Zellpolygone bleibt eine gesonderte Entwicklungsphase.

### Einschränkungen und Freigabe

- Es gibt noch keine produktive CGAL-Engine und keinen Polygonexport.
- Datenverlust, geometrische Äquivalenz oder fachliche Korrektheit sind
  mit den Graphzählungen allein nicht ausgeschlossen.
- Die GPL-Bedingungen des CGAL-Pakets müssen vor einem Produktiveinsatz
  geklärt sein.
- Bestehende Boost-Verarbeitung und originale GIP-Daten bleiben unverändert.
