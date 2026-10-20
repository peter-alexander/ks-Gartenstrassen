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
Ein nicht bestandener, unvollständiger oder veralteter QA-Bericht stoppt den PMTiles-Export.
Für eine **ausdrücklich ungeprüfte** Sichtprüfung kann der Lauf mit
`ALLOW_FAILED_QA=1 bash code/scripts/run-gartenstrassen-wien.sh` fortgesetzt werden.
Ein veralteter QA-Bericht wird zuvor archiviert und neu berechnet; der
bestehende GeoJSON- und PMTiles-Stand wird nicht automatisch überschrieben. Keine fachliche
Freigabe und keine berechneten Gartenstraßen-Potenzialkennzahlen.
Vorhandene Ausgaben werden nicht überschrieben; für eine Neuerzeugung
die betreffende Ausgabe zuvor gesichert/umbenannt entfernen.

Die Pipeline führt noch keinen vollständigen Validierungsbeweis der
CGAL-Site-Identitäten oder der Parabelapproximation.
