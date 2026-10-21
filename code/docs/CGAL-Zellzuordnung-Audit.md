# Original-LINEAR_USE-Schnittzuordnung

Die frühere künstliche Fünf-Punkte-Stichprobe wurde entfernt.

Die neue Zuordnung vergleicht **jede originale LINEAR_USE-Quelllinie**
(`object_id`, `edge_id`, `base_type=1`) mit allen vom vollständigen
CGAL-Voronoi polygonisierten Flächen. Ein STRtree reduziert die
Prüfungen auf tatsächlich schneidende Kandidaten.

- `intersects == 0`: Linien ohne Flächentreffer
- `intersects > 1`: Linien mit mehreren Flächentreffern
- `intersects == 1`: übertrage ursprüngliche `edge_id` als Vorschlag
- mehrere verschiedene Vorschläge pro Fläche: Konflikt
- Flächen ohne eindeutigen Vorschlag: weiterer Diagnoselayer

Alle vier Fallgruppen werden vor dem SIS-Verschnitt in WGS84 als
GeoJSON ausgegeben. Dazu kommt ein JSON-Zählbericht. Die Ausgabepfade
beginnen mit `output/cgal_original_line_intersections_sis_wien__`.

**Achtung:** Ein Schnitt über `intersects` enthält auch reine
Rand-/Endpunktberührungen. Im Mehrfachtreffer-GeoJSON stehen deshalb
`positive_length_hits` und `boundary_only_hits` getrennt.
Es wird keine automatische Entscheidung aus diesen Zahlen abgeleitet.

Falls ein ungeklärter Fall existiert, stoppt der vollständige Lauf vor
dem SIS-Verschnitt. Das verhindert stillschweigend falsche `edge_id`.
