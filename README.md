# Gartenstraßen Wien

Aktuelle Forschungsstufe: Voronoi aus **originalen LINEAR_USE-Linien**
(`base_type=1`) mit CGAL. Anders als bisher bleibt die Identität der
Generatorsegmente im CGAL-Site-Export erhalten und wird auf die
ursprüngliche `edge_id` zurückgeführt.

## Ablauf bis vor SIS

1. LINEAR_USE-Geometrien (EPSG:31256) ohne Mittelachsen laden.
2. Originalsegmente für CGAL millimetergenau segmentieren/noden.
3. CGAL: Dualgrenzen **und tatsächliche Sites** gemeinsam ausgeben.
4. Für jede **Segment-Site** die `edge_id` ihres ursprünglichen
   Eingabesegments bestimmen; polygonisierte Zelle anhand der positiven
   Schnittlänge mit der tatsächlichen Site verbinden. Keine
   künstlichen Prüfpunkte, keine Nearest-Heuristik.
5. Zugeordnete Zellen derselben `edge_id` vereinigen; nur räumlich
   zusammenhängende Teile zu einem Feature zusammenfassen.
6. Ergebnis als GeoJSON **vor SIS** exportieren.

**Punktzellen werden nicht behandelt oder einer `edge_id` zugewiesen.**
Im Zwischenergebnis verbleiben daher bewusst unbelegte Flächen.
Ungültige oder widersprüchliche Segment-Site-Zuordnungen stoppen den
Export. Das ist ein experimenteller Geometrieexport, keine vollständige
Flächenpartition und noch kein SIS- oder PMTiles-Produkt.

```bash
git pull --ff-only
bash code/scripts/run-gartenstrassen-wien.sh
```

Ausgabe: `output/cgal_original_segment_sites_pre_sis_wien.geojson`.
Der bislang fehlerhafte vollständige LINEAR_USE-Linien/Polygon-
Schnittansatz ist nicht mehr Bestandteil des aktiven Wiener Laufs.
Vorhandene Eingabecaches werden wiederverwendet, alte GeoJSON-Ergebnisse
nicht überschrieben.

Der SIS-Verschnitt wird erst nach Prüfung des Vor-SIS-Ergebnisses
wieder aufgenommen.

## Segment-Site-Prüfung und fortsetzbarer Lauf

Die Zuordnung einer CGAL-Segment-Site zu einer polygonisierten Zelle
verwendet die **positive Schnittdimension mit dem Polygoninneren**
(DE-9IM), nicht die bloße Länge von `intersection()`: entlang
von Polygonkanten liegende Segmentanteile zählen nicht als Eigentum.
Echte Treffer in mehreren Polygoninnenflächen werden weiterhin
abgelehnt. Punktzellen bleiben unzugeordnet.

Nach der teuren Polygonisierung wird vor der Zuordnung ein geprüfter
SQLite-Zwischenspeicher erzeugt:
`output/cgal_original_segment_sites_pre_sis_wien__geometry_checkpoint.sqlite`.
Er wird nur wiederverwendet, wenn Eingangsdaten, AOI, CGAL-Binary und
Geometrieerzeugungscode identisch sind. Nach einem Fehler können so
nur die Zuordnung und der Dissolve erneut ausgeführt werden.

Ein Zuordnungsbericht und eine kleine, kartierbare Problemgeometrie
werden auch bei einem Fehler gespeichert:

- `output/cgal_original_segment_sites_pre_sis_wien__site_zuordnung.json`
- `output/cgal_original_segment_sites_pre_sis_wien__site_konflikte.geojson`

Ältere Berichte werden archiviert, nicht überschrieben.


## Native CGAL-Voronoi-Faces (aktuelle Stufe)

**Aktiver Wiener Lauf:** `bash code/scripts/run-gartenstrassen-wien.sh`.

Anders als die bisherigen Debug-Auswertungen werden Voronoi-Zellen
nun direkt mit `CGAL::Voronoi_diagram_2` ausgelesen. Jede Segment-Face
enthält ihre eigene CGAL-Site samt ursprünglichem unterstützenden
Eingabesegment. Die bereits während des Nodens erhaltene `edge_id`
wird über genau dieses Segment übernommen. Der C++-Exporter liefert
die Rand-Halfedges einer Face in Umlaufrichtung und linearisiert die
CGAL-Bisektoren. Python setzt diese explizite Face-Geometrie zusammen,
schneidet sie auf das Wiener Untersuchungsfenster zu und vereinigt
zusammenhängende Face-Polygone gleicher `edge_id`.

**Punkt-Faces werden vollständig ausgelassen**, nicht einmal
nachträglich einer `edge_id` zugewiesen. Keine räumliche
Eigentümersuche, keine zufälligen Prüfpunkte oder Ersatz-Zuordnung.
Die Ausgabe ist **vor SIS**, ein direkter Vergleich mit dem QGIS
Cluster Generator ist möglich.

Ausgabe:
`output/cgal_native_faces_dissolved_pre_sis_wien.geojson`

Der native Face-Stream wird zur Wiederverwendung getrennt gespeichert:
`output/cgal_native_faces_dissolved_pre_sis_wien__native_faces.txt`
und `__native_faces_meta.json` mit Prüfsummen der Quellen und
CGAL-Version. Bestehende Dateien werden nicht still überschrieben.

Die frühere `site_intersections`-Methode bleibt ausschließlich
historische Diagnose und gehört **nicht** zum aktiven Lauf.

## Fehlerhafte native CGAL-Face untersuchen (ohne erneuten CGAL-Lauf)

Wenn der direkte Face-Export bei einer konkreten Face anhält, z. B.
`Face 54 ... native Polygongeometrie ungültig`, ist der rohe
CGAL-Face-Stream bereits gespeichert. Zur **reinen Untersuchung**:

```bash
cd /home/openclaw/.openclaw/workspace/ks-Gartenstrassen
git pull --ff-only
cd code
../.venv/bin/python -m scripts.inspect_cgal_native_face \
	--stream ../output/cgal_native_faces_dissolved_pre_sis_wien__native_faces.txt \
	--cache ../cache/wien/linear_use_original.sqlite \
	--face 54 \
	--report ../output/cgal_face54_report.json \
	--geojson ../output/cgal_face54_edges.geojson \
	--raw ../output/cgal_face54_native.txt
```

Das erzeugt einen verständlichen Gültigkeitsbericht, einen in QGIS
darstellbaren Linien-/Halfedge-Diagnoselayer und die exakten, nummerierten
nativen Face-Records. Es wird **keine** Geometrie repariert, keine Face
einer anderen `edge_id` zugeordnet und kein SIS-Verschnitt ausgeführt.
Die Fehlerursache muss anhand dieser Geometrie geklärt werden, bevor der
Vor-SIS-Export wieder freigegeben wird.
