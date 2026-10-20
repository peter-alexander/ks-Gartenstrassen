# Wien-Komplettlauf: GeoJSON und PMTiles (experimentell)

Ein zentraler Einstiegspunkt nutzt vorhandene, unveränderte Rohdaten und Caches,
erstellt falls erforderlich die LINEAR_USE-Mittelachsen und CGAL/SIS-Flächen,
prüft deren Zellzuordnung stichprobenartig und erzeugt anschließend aus dem
GeoJSON direkt eine Vektor-PMTiles-Datei.

```bash
git pull --ff-only
bash code/scripts/run-gartenstrassen-wien.sh
```

Voraussetzungen: `.venv`, CGAL/CMake wie in `code/cgal/README.md`
beschrieben, sowie **felt/tippecanoe ab Version 2.17** mit direktem
PMTiles-Export. Die GIP-Quelldatei wird nur bei noch fehlender
`cache/wien/linear_use.sqlite` gebraucht:
`GIP_NETWORK_SOURCE=/pfad/gip_network_ogd.gpkg bash code/scripts/run-gartenstrassen-wien.sh`.

Ausgaben:
- `output/cgal_segment_voronoi_sis_wien.geojson` (vollständige Debugflächen)
- `output/cgal_cell_ownership_audit.json` (Stichproben)
- `output/cgal_segment_voronoi_sis_wien.pmtiles` (Vektorlayer `gartenstrassen`, Z8–15)

Die PMTiles dienen der schnellen Sichtprüfung. Es werden keine Geometrien
bewusst verworfen, aber die Vektorkacheln sind zoomabhängig vereinfacht.
Fehler im geometrischen Zellzuordnungs-Audit werden ausdrücklich gemeldet,
verhindern die *experimentelle* Vorschau jedoch nicht. Keine fachliche
Freigabe und keine berechneten Gartenstraßen-Potenzialkennzahlen.
Vorhandene Ausgaben werden nicht überschrieben; für eine Neuerzeugung
die betreffende Ausgabe zuvor gesichert/umbenannt entfernen.

Die Pipeline führt noch keinen vollständigen Validierungsbeweis der
CGAL-Site-Identitäten oder der Parabelapproximation.
