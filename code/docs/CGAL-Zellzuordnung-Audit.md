# Stichprobenprüfung der CGAL/SIS-Zuordnung

Die Prüfroutine vergleicht mehrere Stichproben je exportiertem Polygon
mit **allen originalen LINEAR_USE-Linien**. Gemessen wird der Abstand
zur nächstgelegenen Linie der zugewiesenen `edge_id` gegenüber dem
Abstand zur nächstgelegenen beliebigen Original-Linie.

```bash
cd code
../.venv/bin/python -m scripts.audit_cgal_cell_ownership \
	--cache ../cache/wien/linear_use_original.sqlite \
	--geojson ../output/cgal_original_linear_use_sis_wien.geojson \
	--out ../output/cgal_original_cell_ownership_audit.json
```

Die Flächenbilanz und die Gültigkeit der Ausgabegeometrie werden zusätzlich
im CGAL/SIS-Exporter überprüft. Stichproben allein beweisen keine
vollständige geometrische Korrektheit. Auffälligkeiten werden gemeldet,
nicht automatisch korrigiert.
