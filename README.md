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


## CGAL-Faces außerhalb von Wien ignorieren

Der native CGAL-Export enthält auch Zellen weit außerhalb Wiens, weil
der künstliche Voronoi-Rahmen die Stadt mit großem Abstand umschließt.
Diese Bereiche dürfen die Ausgabe **vor SIS** nicht blockieren.

`read_native_faces` schließt jetzt anhand der **gesamten Randkurven-
Bounding-Box** jede Face aus, deren Hülle vollständig außerhalb der
AOI-Hülle liegt. Diese Prüfung passiert **vor** der Polygon-Gültigkeit.
Für verbleibende Faces gilt unverändert die strenge Gültigkeitsprüfung.

Danach wird direkt mit der **bereits vorhandenen** geometrischen Wiener
AOI aus `cache/wien/aoi.geojson` geschnitten – nicht nur mit deren
rechteckigem Bounds-Ausschnitt. Eine zusätzliche Wiener Grenzdatei ist
dafür nicht erforderlich.

Der gespeicherte CGAL-Face-Stream
(`__native_faces.txt` + `__native_faces_meta.json`) bleibt gültig:
Bei erneutem Start des bestehenden Wiener Laufs wird nur die
Vorverarbeitung/Polygonvereinigung wiederholt, nicht CGAL neu berechnet.


## CGAL-Vorschau vor jeder Geometrieprüfung (QGIS)

Für eine **reine visuelle Kontrolle** kann die gespeicherte native
Voronoi-Face-Ausgabe ohne vollständigen GIS-Export dargestellt werden:

```bash
cd /home/openclaw/.openclaw/workspace/ks-Gartenstrassen
git pull --ff-only
bash code/scripts/run-gartenstrassen-wien.sh --preview-only
```

Der native CGAL-Face-Stream aus dem bereits erfolgten Lauf wird
wiederverwendet; **kein neuer CGAL-Lauf** nötig. Ausgabe:

- `output/cgal_native_faces_dissolved_pre_sis_wien__preview.geojson`
- `output/cgal_native_faces_dissolved_pre_sis_wien__preview_report.json`

Die Vorschau wird auch beim normalen Hauptlauf **vor** den strengen
CGAL-Randkurven-/Polygon- und Dissolve-Prüfungen erstellt. Bei
`--preview-only` endet die Verarbeitung nach dem GeoJSON
erfolgreich; die spätere strenge Prüfung wird nicht gestartet.

Jede **native Segment-Face** ist ein eigenes GeoJSON-Feature mit der
ursprünglichen `edge_id` und `face_number`; die
vorläufige Darstellung kann in QGIS nach `edge_id` eingefärbt
werden. Punkt-Faces kommen weiterhin nicht vor.

Die Vorschau ist **nicht** nach `edge_id` vereinigt und
absichtlich **nicht** topologisch geprüft. Verbogene CGAL-Halfedge-Kurven,
die sich nicht mit ihrem eigenen CCB-Endpunkt verbinden lassen (z. B.
Face 282), werden **nur für die Darstellung** als gerade CCB-Sehne
eingetragen. Die betroffenen Features erhalten `fallback: true`;
Details stehen im JSON-Bericht. Selbstüberschneidende Polygone bleiben
im Vorschau-Layer erhalten, ohne automatische `make_valid`-
Reparatur. Der Vorschau-Layer wird nur anhand der AOI-Bounding-Box
gefiltert, **nicht auf die Wiener Grenze geclippt**. Die ungeprüften
Polygone sind ausdrücklich keine Grundlage für SIS oder PMTiles.

Der strenge endgültige Export bleibt unverändert aktiv und bricht bei
fehlerhafter Geometrie weiterhin ab. Beide Vorschau-Dateien werden
bei unveränderter Eingabe wiederverwendet, bei abweichenden Prüfsummen
aber nicht still überschrieben.


## Selektive Punkt-Faces ursprünglicher LINEAR_USE-Stützpunkte

**Aktuelle Variante:** Originale Linien-Stützpunkte `A—B—C—D—E—F`
liefern alle fünf **Segment-Faces** und zusätzlich nur die nativen
**Punkt-Faces B, C, D und E**. A und F sind Linien-Endpunkte
und werden nicht als Punkt-Faces übernommen.

Maßgeblich ist ausschließlich die originale `LINEAR_USE`-
Koordinatenfolge (EPSG:31256, millimetergenau für CGAL umgesetzt).
Weder beim Noding hinzugekommene Punkte noch die künstlichen
Rahmeneckpunkte werden als innere Original-Stützpunkte behandelt.
Sollte ein Stützpunkt in mehreren verschiedenen `edge_id`-
Linien vorkommen, wird er wegen unklarer eindeutiger Herkunft
konservativ nicht zugeordnet.

CGAL exportiert nun **begrenzt** liegende Segment- und Punkt-Faces
mit nativen Generatoren (`F` beziehungsweise `P`).
Die Zuordnung zu `edge_id` erfolgt ohne räumliche
Suche ausschließlich über den ursprünglichen Generator.
Damit der vorherige Versuch einschließlich Cache und Vorschau
erhalten bleibt, nutzt diese Version eine neue Ausgabe:

`output/cgal_native_faces_inner_points_pre_sis_wien__preview.geojson`

Sofortige **visuelle Ausgabe ungeprüfter Einzel-Faces**:

```bash
cd /home/openclaw/.openclaw/workspace/ks-Gartenstrassen
git pull --ff-only
bash code/scripts/run-gartenstrassen-wien.sh --preview-only
```

`generator_type=segment` bezeichnet die normalen
Voronoi-Segmentzellen; `generator_type=inner_point`
die selektiv hinzugekommenen Punktzellen. Die nicht geprüfte
Vorschau behält mögliche Ersatzsehnengeraden und
topologische Unstimmigkeiten, die im
`__preview_report.json` dokumentiert werden.
Sie ist **noch nicht vereinigt**, nicht SIS-geschnitten und
nicht für eine fertige GIS-Karte freigegeben.

Bei strenger Verarbeitung werden die ausgewählten Punkt-Faces
mit den Segment-Faces gleicher originaler `edge_id`
vereinigt; die regulären strengen Geometrieprüfungen bleiben
aktiv. Ein neuer CGAL-Lauf ist einmalig nötig, da der vorige
gespeicherte Face-Stream nur Segment-Faces enthält.

## Nächster Schritt: native Voronoi-Faces nach originaler edge_id vereinigen

Der **normale Wiener Lauf** erzeugt nun statt eines strengen
Face-Exports (der bei einer fehlerhaften linearen Halfedge früh abbrechen
konnte) direkt ein GeoJSON aus **nach edge_id vereinigten Flächen**:

```bash
cd /home/openclaw/.openclaw/workspace/ks-Gartenstrassen
git pull --ff-only
bash code/scripts/run-gartenstrassen-wien.sh
```

Der native CGAL-Face-Stream und die Vorschau der Segment-Faces samt
ursprünglichen inneren Punkt-Faces werden wiederverwendet. Danach folgt
ein eigenständiger Dissolve pro `edge_id`. Pro `edge_id` wird genau
**ein gültiges, zusammenhängendes Polygon** angenommen und geprüft.
Kein `MultiPolygon`-Fallback, kein `make_valid`, keine heuristische
Neu-Zuordnung und kein SIS-Verschnitt.

Die Ergebnisse liegen in folgenden Dateien:

- **Vereinigte Polygone:**
  `output/cgal_native_faces_inner_points_pre_sis_wien.geojson`
- **Problematische Original-Faces für QGIS:**
  `output/cgal_native_faces_inner_points_pre_sis_wien__dissolve_debug.geojson`
- **Vollständiger Diagnosebericht mit `edge_id` und Ursache:**
  `output/cgal_native_faces_inner_points_pre_sis_wien__dissolve_report.json`

Ergibt die Vereinigung einer `edge_id` mehrere getrennte Flächen,
etwas anderes als `Polygon`, oder schlägt sie wegen ungültiger
Original-Faces fehl, wird die ganze `edge_id` **nur im Debug** geführt.
Andere `edge_id` werden trotzdem ausgegeben. Debug-Features enthalten
die ursprünglichen Vorschau-Faces mit `face_number`, `generator_type`
und `dissolve_error`.

**Wichtige Genauigkeitsgrenze:** Die Vorschau kann fehlerhafte
CGAL-Halfedges durch gerade Endpunkt-Sehnen ersetzen. Das gilt auch
für einen Dissolve, der formal gültige Polygone erzeugt. Daher sind
diese Outputs weiterhin als **prüfpflichtiges Zwischenprodukt**
(`preview_based=true`) markiert, nicht als geprüfter CGAL-/SIS-Export.

Wer die bereits vorhandene Vorschau **ohne** erneute
Segmentaufbereitung/CGAL-Verifikation sofort vereinigen möchte, kann
direkt diesen Schritt ausführen:

```bash
cd /home/openclaw/.openclaw/workspace/ks-Gartenstrassen/code
../.venv/bin/python -m scripts.dissolve_cgal_preview \
	--preview ../output/cgal_native_faces_inner_points_pre_sis_wien__preview.geojson \
	--out ../output/cgal_native_faces_inner_points_pre_sis_wien.geojson \
	--debug ../output/cgal_native_faces_inner_points_pre_sis_wien__dissolve_debug.geojson \
	--report ../output/cgal_native_faces_inner_points_pre_sis_wien__dissolve_report.json
```

Dabei ist keine weitere CGAL-Berechnung nötig. Bestehende Dateien
werden nicht automatisch gelöscht oder überschrieben.
