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


## TURN_USE-Kreuzungshüllen wieder vor dem Dissolve abziehen

Wiederaufnahme der **historischen SIS-V2-Regel** vom 17.10.2026
(`scripts/sis_gip2.py` im Commit `07374b16c192`):

1. `NODE` und `TURN_USE` mit RTree aus der **originalen**
   `gip_network_ogd.gpkg` im Wiener Bereich laden.
2. Alle TURN_USE-Linien nach `via_node_id` gruppieren
   (`NODE.object_id`), **ohne `base_type`-Filter**.
3. Aus sämtlichen Stützpunkten pro NODE eine konvexe Hülle
   (`MultiPoint(coords).convex_hull`) bilden. Keine
   pauschalen Radien oder künstlichen Flächen bei kollinearen Linien.
4. Hüllen auf die vorhandene Wiener AOI begrenzen.
5. **Für jede einzelne** CGAL-Segment- und innere Punkt-Face zunächst
   diese TURN_USE-Hüllen abziehen.
6. Erst **danach** die gekürzten Faces derselben originalen
   `edge_id` vereinigen.

Ergebnis **wie zuvor**, ohne SIS-Verschnitt:

- `output/cgal_native_faces_inner_points_pre_sis_wien.geojson`:
  pro erfolgreicher `edge_id` ein zusammenhängendes Polygon
- `output/cgal_native_faces_inner_points_pre_sis_wien__dissolve_debug.geojson`:
  Verbleibende, **bereits um die TURN_USE-Hüllen gekürzte**
  Face-Geometrien problematischer `edge_id` mit Fehlergrund
- `output/cgal_native_faces_inner_points_pre_sis_wien__dissolve_report.json`:
  Anzahl und Wirkung der TURN_USE-Hüllen sowie Fehlerstatistik

**Lauf:**

```bash
cd /home/openclaw/.openclaw/workspace/ks-Gartenstrassen
git pull --ff-only
bash code/scripts/run-gartenstrassen-wien.sh
```

Verwendet standardmäßig dieselbe Original-GPKG wie der LINEAR_USE-
Importer: `/mnt/c/Users/peter/Downloads/gip_network_ogd.gpkg`.
Abweichender Pfad via `GIP_NETWORK_SOURCE` setzen.

Der zuvor erzeugte native CGAL-Stream und die selektive Vorschau bleiben
erhalten und werden wiederverwendet. Die bestehenden *regulären und
Debug-Dissolve-Ergebnisse* werden nach einer erfolgreichen neuen
Verarbeitung atomar ersetzt. **Keine neue CGAL-Berechnung** nötig.

Eine `edge_id`, die nach dem TURN_USE-Abzug nur noch
getrennte Teilflächen, gar keine Fläche oder keine gültige
Polygongeometrie ergibt, kommt wie bisher nur in die Debug-Ausgabe.
Die zugrunde liegende Vorschau kann ersatzweise linearisierte
CGAL-Kurven enthalten; die resultierenden Polygone sind deshalb
weiterhin **prüfpflichtige Zwischenprodukte**.


### Debug-Geometrie ist jetzt immer nach dem TURN_USE-Abzug

Die Datei `output/cgal_native_faces_inner_points_pre_sis_wien__dissolve_debug.geojson`
zeigt jetzt ausschließlich die **nach den konvexen TURN_USE-Hüllen
verbleibenden Face-Geometrien** der beim Dissolve gescheiterten
`edge_id`. Bei einer getrennten Fläche bleibt im
Debug eine `MultiPolygon`-Quellgeometrie erhalten; der
reguläre Output akzeptiert weiterhin nur ein einzelnes Polygon.

- `turn_use_cut_status=unchanged`: kein Überlappen der
  Face mit einer der Hüllen, Geometrie deshalb unverändert.
- `turn_use_cut_status=cut`: GeoJSON enthält die
  tatsächlich beschnittene Geometrie (EPSG:4326).
- `turn_use_cut_status=fully_removed`: vollständig
  entfernt; **kein** Polygon wird zurückgeholt. Es bleibt ein
  Debug-Datensatz mit `geometry: null` und
  der ursprünglichen `face_number` als Nachweis.
- `source_invalid`, `source_not_polygon`,
  `cut_failed`, `source_error`:
  die Geometrie lässt sich nicht sicher nach dem Abzug darstellen,
  daher ebenfalls `geometry: null`. Die Ursache steht
  in `dissolve_error_detail` bzw.
  `turn_use_cut_note`.

Auch wenn eine Face innerhalb einer `edge_id` ungültig
ist, werden die anderen Faces derselben Gruppe dennoch einzeln
beschnitten und für die Diagnose ausgegeben. Es findet **keine**
automatische Geometriereparatur und keine Rückkehr zur unbeschnittenen
Quellfläche statt.

Der normale Wiener Lauf regeneriert bei vorhandenem CGAL-Stream und
Vorschau die bisher benannte reguläre Ausgabe, die beschnittene
Debug-Ausgabe und den Fehlerbericht. CGAL muss nicht erneut laufen.


## Automatische Rettungsversuche durch TURN_USE-Hüllenpuffer (1–4 m)

Nachdem alle originalen CGAL-Faces einer `edge_id` zunächst
um die **ungepufferten** TURN_USE-Hüllen gekürzt und vereinigt wurden,
bleiben **bereits erfolgreiche Einzelpolygone unverändert**.

Nur für verbleibende problematische `edge_id` erfolgen
vier zusätzliche Versuche in EPSG:31256:

1. Originale TURN_USE-Hüllen um **1 m** puffern, den aktuellen
   Restflächen abziehen, erneut nach `edge_id` vereinigen.
2. Falls immer noch nicht genau ein gültiges Polygon:
   **2 m** Puffer und erneut ausschneiden/vereinigen.
3. Falls weiterhin erfolglos: **3 m**.
4. Letzter Versuch: **4 m**.

Die angegebenen Puffer sind **absolute Abstände um die ursprünglichen
Hüllen**, nicht 1+2+3+4 = 10 m. Die zusätzlichen Zuschnitte werden
auf die jeweils schon **verbliebenen Restgeometrien** angewandt.

Sobald eine `edge_id` als gültiges, zusammenhängendes
Einzelpolygon vereinigt werden kann, landet sie in der **normalen**
Ausgabe (mit `recovered_by_buffer=true` und
`turn_use_buffer_m` = erfolgreicher Wert).
Ohne Rettungsbedarf bleibt `turn_use_buffer_m=0`.

Nach erfolglosem vierten Versuch verbleibt die `edge_id`
in `__dissolve_debug.geojson`. Die Debug-Geometrien
zeigen die **tatsächlich nach bis zu 4 m ausgeschnittenen Restflächen**;
vollständig entfernte Faces und nicht sicher auswertbare
Quellen bleiben `geometry:null`. Das Debug-Attribut
`last_turn_use_buffer_m` und die Fehlerliste im
`__dissolve_report.json` bezeichnen die zuletzt
versuchte Stufe. Der Bericht enthält pro Stufe Versuchszahlen
und gerettete `edge_id` samt erfolgreichem Pufferabstand.

Die bestehenden drei Ergebnisdateien werden vom normalen
`run-gartenstrassen-wien.sh` nach erfolgreichem Lauf
ersetzt, die native CGAL-Vorschau und der CGAL-Face-Stream
unverändert wiederverwendet. Dies ist weiterhin eine experimentelle
Vorschau- und Diagnosepipeline, **kein** SIS-Verschnitt.


## Original-Faces statt gepufferter Restfläche bei erfolgreicher Rettung

Die 1–4-m-TURN_USE-Pufferschleife dient bei fehlgeschlagenen
`edge_id`-Dissolves ab sofort **nur zur Auswahl der
ursprünglichen CGAL-Faces**, nicht mehr zur endgültigen Ausgabe der
stark gekürzten Restgeometrie:

1. Für eine problematische `edge_id` werden die bereits
   verbliebenen Flächen nacheinander um die absoluten
   TURN_USE-Puffer von 1, 2, 3 und 4 m weiter ausgeschnitten.
2. Liefert eine Stufe genau **ein gültiges, zusammenhängendes Polygon**,
   ist dies nur ein **räumlicher Auswahlkandidat**.
3. Der Kandidat wird gegen die **ursprünglichen ungepufferten und nicht
   um TURN_USE gekürzten CGAL-Segment-/inneren Punkt-Faces derselben
   originalen `edge_id`** gematcht. Nur ein
   **Flächenschnitt größer als null** zählt; reine Randberührung nicht.
   Andere `edge_id` werden niemals räumlich neu zugeordnet.
4. Die getroffenen **Original-Faces** werden ohne neue Clipping-Maske
   vereinigt. Das reguläre Ergebnis darf nun `Polygon`
   **oder `MultiPolygon`** sein. Unmögliche bzw. ungültige
   Original-Vereinigungen bleiben im Diagnosemodus; der nächste
   Pufferdurchgang wird versucht, statt den gepufferten Kandidaten als
   Ersatz auszugeben.

Die **bei 0 m bereits regulär erfolgreichen** Einzelpolygone bleiben
weiterhin wie bisher nach dem ersten TURN_USE-Abzug bestehen.
Nur **neu durch 1–4 m gerettete** `edge_id` erhalten im
regulären Output die vollständige Original-Face-Vereinigung.

Die bisherigen Ergebnis- und Debugdateien werden auf derselben
Position **ersetzt**, der native CGAL-Face-Stream und die Vorschau
weiterverwendet. Neue reguläre Attribute sind
`geometry_from_original_faces`,
`matched_original_face_count`,
`buffer_candidate_area_m2` und wie bisher
`turn_use_buffer_m`. Der JSON-Bericht protokolliert
die `matched_original_face_numbers`, die Größe des
Auswahlkandidaten und die Fläche der wiederhergestellten Originalunion.


## Letzter Rettungsschritt: Debug-Restflächen ab 250 m²

Wenn eine `edge_id` nach dem ungepufferten TURN_USE-Ausschluss,
den vier Pufferstufen **1–4 m** und dem gegebenenfalls erfolgreichen
Matching auf ursprüngliche CGAL-Faces noch immer problematisch ist,
folgt ein abschließender **Flächenfilter direkt auf den verbleibenden
Debug-Geometrien**:

1. Für jede noch verbliebene Face (in **EPSG:31256**) alle
   `MultiPolygon`-Teile in einzelne Polygonkomponenten zerlegen.
2. Komponenten mit **Fläche kleiner als 250 m²** vollständig verwerfen.
   Genau **250 m² bleiben enthalten**. Die Grenze wird je Komponente
   und **nicht** über die Summe einer gesamten MultiPolygon-Face geprüft.
3. Die ausreichend großen Restkomponenten **derselben originalen
   `edge_id`** mit `union_all` vereinigen.
   Ein gültiges `Polygon` **oder `MultiPolygon`
   wird zusätzlich in das **reguläre** GeoJSON übernommen.
4. Hier erfolgt **keine Rückübernahme der ursprünglichen CGAL-Faces**:
   Das reguläre Endergebnis enthält exakt die ausreichend großen,
   bereits durch TURN_USE (bis 4 m) ausgeschnittenen **Restflächen**.
5. Wenn eine Geometrie nicht verarbeitet werden kann, bleibt ein
   Debug-Nachweis mit Fehlergrund erhalten. Sind ausschließlich
   Komponenten unter 250 m² vorhanden, erscheint die `edge_id`
   nicht im Kartenoutput; die Verwerfung steht im JSON-Bericht.

Reguläre Zusatzattribute:
`recovered_by_debug_area_filter=true`,
`debug_area_threshold_m2=250`,
`debug_kept_components`,
`debug_discarded_components` und
`partial_source_errors` (wenn zwar gültige große
Teilflächen ausgegeben werden konnten, andere Quell-Faces aber
geometrisch nicht verarbeitbar waren). Bei solchen Teilrettungen
bleiben die nicht verarbeitbaren Quell-Faces im Debug-Bericht.

Der `__dissolve_report.json` dokumentiert die Gesamtzahl
der verworfenen Polygonkomponenten, die verworfene Fläche in m²,
die zusätzlich übernommenen `edge_id`, die vollständig
verworfenen `edge_id` und verbleibende Fehler.

**Die bestehenden drei Ergebnisdateien behalten ihre Namen und werden
beim nächsten normalen Wiener Lauf ersetzt.** Native CGAL-Dateien,
TURN_USE-Berechnung und Vorschau bleiben unverändert.
