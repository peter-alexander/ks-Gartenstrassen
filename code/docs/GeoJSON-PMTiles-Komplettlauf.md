# Aktueller Zwischenschritt: CGAL vor SIS

```bash
git pull --ff-only
bash code/scripts/run-gartenstrassen-wien.sh
```

Verwendet den bestehenden Original-LINEAR_USE-Cache,
führt eine CGAL-Voronoi-Berechnung mit Site-Provenienz durch
und vereinigt vor dem SIS-Verschnitt die Segmentzellen mit
identischer `edge_id`.

Ausgabe:
`output/cgal_original_segment_sites_pre_sis_wien.geojson`

Punktzellen bleiben ausdrücklich unzugeordnet. Der Export
ist vorläufig und darf noch nicht als vollständig validierte
SIS- oder PMTiles-Karte verwendet werden. SIS und PMTiles
bleiben während dieser Qualitätskontrolle ausgesetzt.


## Aktuelle native Vor-SIS-Ausgabe

```bash
cd /home/openclaw/.openclaw/workspace/ks-Gartenstrassen
git pull --ff-only
bash code/scripts/run-gartenstrassen-wien.sh
```

Die aktuelle Pipeline benutzt den direkten Export nativer CGAL-
Voronoi-Faces mit der ursprünglichen `edge_id` und führt den Dissolve
**vor SIS** aus. Ergebnis:
`output/cgal_native_faces_dissolved_pre_sis_wien.geojson`

Punkt-Faces bleiben unangetastet und erzeugen bewusst Lücken.
Die Geometrie ist ein kontrollbedürftiges Zwischenprodukt, kein
SIS-/PMTiles-Endergebnis.
