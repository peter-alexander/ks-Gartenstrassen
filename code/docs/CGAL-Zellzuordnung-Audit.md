# CGAL/SIS: unabhängige Stichprobenprüfung der Zellzuordnung

Die aktuelle CGAL-Pipeline gruppiert polygonisierte Teilflächen nach der am
Repräsentationspunkt nächstgelegenen Achse. Eine korrekte Flächenbilanz
allein beweist nicht, dass jede `edge_id` richtig ist.

## Separater Prüflauf

Nach einem vorhandenen Wiener CGAL-Debugexport:

```bash
cd code
../.venv/bin/python -m scripts.audit_cgal_cell_ownership \
	--cache ../cache/wien/linear_use.sqlite \
	--geojson ../output/cgal_segment_voronoi_sis_wien.geojson \
	--out ../output/cgal_cell_ownership_audit.json
```

Die Prüfung liest nur die Mittelachsen und das bereits exportierte GeoJSON.
Sie verändert **weder** die ursprünglichen Daten **noch** die Zuordnung.
Sie transformiert die Polygonflächen nach EPSG:31256, prüft den
Repräsentationspunkt sowie bis zu vier zusätzliche Teilflächenproben je
Polygonkomponente und vergleicht die Entfernung zur zugewiesenen Achse
mit der tatsächlich nächstgelegenen Achse (STRtree). Differenzen über
1 cm werden mit Position und beiden `edge_id` protokolliert. Ein
auffälliger Bericht führt zu Exit-Code 1; bestehende Berichte werden
nicht überschrieben.

**Wichtige Grenze:** Die Proben können falsche Zuordnungen erkennen, aber
nicht deren Abwesenheit beweisen. Auch die STRtree-Abfrage verwendet
Mittelachsen statt interner CGAL-Site-Identitäten; Noding und die
approxmierten Voronoi-Grenzen werden damit nicht vollständig validiert.
Ein rigoroser Nachweis benötigt die originalen CGAL-Site-Zuordnungen und
eine geometrische Grenze für die Parabelapproximation. Diese
Stichprobe ist daher bewusst nur eine zusätzliche Diagnose.
