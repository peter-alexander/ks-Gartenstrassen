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
