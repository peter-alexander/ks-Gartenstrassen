# CGAL-Segment-Voronoi: nicht endliche Vertices

## Befund und lokale Reproduktion

Der gespeicherte Wiener Face-Stream wurde nicht als Erklärung, sondern als
Ausgangspunkt verwendet. Die beiden Fehlergruppen lassen sich mit den
originalen Integer-Millimeter-Sites und einem künstlichen Rahmen ohne den
vollständigen Wien-Lauf reproduzieren:

| Gruppe | Segment 1 | Segment 2 | dritte Punkt-Site |
|---|---|---|---|
| A | `(18322833 10460171)–(18327970 10494392)` | `(18327970 10494392)–(18339843 10573486)` | `(18329781 10494793)` |
| B | `(33290069 12201293)–(33322433 12199793)` | `(33322433 12199793)–(33339327 12199010)` | `(33328587 12188767)` |

Die Determinanten der aufeinanderfolgenden Segmentvektoren betragen nur `-55`
beziehungsweise `-12`, obwohl die Vektorlängen zwischen rund 17 000 und
80 000 mm liegen. Die Segmente sind daher beinahe kollinear und haben zugleich
einen exakt gemeinsamen Endpunkt.

Mit CGAL 5.6 und
`Segment_Delaunay_graph_filtered_traits_2<Simple_cartesian<double>>` entstehen
in jeder Minimalgeometrie 12 nicht endliche `H`/`S`-Records. Der
Segment-Delaunay-Graph besteht zu diesem Zeitpunkt bereits und besteht
`is_valid(false, 1)`. Die Face- und Halfedge-Zahlen sind stabil. Der Fehler
entsteht bei `Construct_svd_vertex_2` für genau die oben genannten drei Sites:

1. Die `Field_with_sqrt`-Intervallkonstruktion wertet einen durch starke
   Auslöschung numerisch knapp negativen Radikanden aus.
2. Sie liefert `NaN`, wirft aber keine `Uncertain_conversion_exception`.
3. CGALs `Filtered_construction` führt deshalb seinen eingebauten exakten
   Fallback nicht aus.
4. Derselbe Vertex wird sowohl über `Voronoi_diagram_2::Vertex::point()` für
   `H` als auch in `draw_dual_edge()` für die Kurvenabtastung von `S`
   angefordert. Daher erscheint derselbe Konstruktionsfehler in mehreren
   Faces und Recordarten.

Das Problem liegt damit nicht in den Delaunay-Prädikaten, der
Generatorzuordnung oder erst in der Stream-Serialisierung. Es liegt in der
approximativen Konstruktion eines einzelnen Voronoi-Vertex; die
Dualkantenzeichnung übernimmt den bereits ungültigen Vertex.

## Gewählte Korrektur

Der etablierte gefilterte Double-Trait bleibt für Graph, Prädikate, Topologie
und alle regulären Konstruktionen unverändert. Nur wenn seine
Vertex-Konstruktion `NaN` oder `Inf` zurückgibt, wird dieselbe Site-Dreiergruppe
mit
`Exact_predicates_exact_constructions_kernel_with_sqrt` algebraisch exakt
ausgewertet. Erst das fertige Ergebnis wird nach `double` konvertiert.

Für die beiden Regressionen ergeben sich:

| Gruppe | gemeinsamer Voronoi-Vertex (mm) | Abstand zu allen drei Sites |
|---|---|---|
| A | `(18328952.554377057, 10494244.506292142)` | `993.563031584` mm |
| B | `(33322088.988644172, 12192370.61274408)` | `7430.355064853` mm |

Die maximale Differenz der drei unabhängig geprüften Abstände liegt in beiden
Fixtures unter `2e-9` mm. Die ursprünglichen `F`- und `P`-Generatoren sowie die
Face-/Halfedge-Zahlen bleiben erhalten.

Der CORE-Gleitkommafilter ist während dieses seltenen exakten Fallbacks
deaktiviert. Das verhindert, dass dieselbe approximative negative Wurzel eine
cwd-relative Datei `Core_Diagnostics` erzeugt; die algebraisch exakte
Auswertung selbst bleibt aktiv.

## Verworfene Alternativen

- **Gesamter Graph mit algebraisch-exaktem Kernel:** geometrisch korrekt,
  aber bereits die Kurvenabtastung einer kleinen Fixture lief um Größenordnungen
  langsamer. Das wäre für 732 000 Sites unverhältnismäßig.
- **`Field_tag`/rationale Ring-Konstruktion mit Double-Ausgabe:** erzeugte
  endliche Werte, aber die bekannten gemeinsamen Vertices waren nicht zu den
  drei Generator-Sites äquidistant. Dieser Ansatz ist fachlich falsch.
- **Halfedge-Sehne, Interpolation, Überspringen oder Geometriereparatur:** würde
  die fehlende Voronoi-Geometrie nur verdecken und wurde nicht verwendet.

## Sicherheitsprüfungen

Der Exporter prüft vor dem Schreiben sämtliche Koordinaten in `F`, `P`, `H`,
`S`, `R` und `L`. Ein verbleibender nicht endlicher Wert beendet den Prozess
mit Face-Nummer, Generator, Halfedge und Berechnungsstelle. Ein bereits
angelegter unvollständiger Ausgabestream wird dabei entfernt. Der CTest baut
zusätzlich einen ausschließlich für den Test bestimmten Exporter ohne exakten
Fallback und weist damit den Fail-fast-Pfad samt Diagnose nach.

## Laufzeit, Speicher und Caches

Auf den lokalen Minimalfällen blieb die Laufzeit gerundet bei `0.02 s`; der
maximale Resident Set stieg wegen CORE von etwa 5.3 MiB auf etwa 6.5 MiB. Auf
regulärer Geometrie wird der exakte Fallback nicht betreten. Im alten Wiener
Stream entsprechen die 24 ungültigen Records nur 12 Aufrufen pro Gruppe;
deshalb ist für den Gesamtprozess nur ein kleiner Zusatzaufwand zu erwarten.
Ein vollständiger Wien-Benchmark wurde nicht durchgeführt.

Die Face-Cache-Identität heißt nun
`cgal-native-face-stream-v3-exact-vertex-fallback`, enthält die Methode
explizit und weiterhin die SHA-256 des Binaries. Der alte native Face-Stream,
seine Meta-Datei und die davon abhängige Preview samt Bericht müssen gemeinsam
archiviert und neu erzeugt werden. Unverändert wiederverwendbar bleiben:

- `linear_use_original.sqlite` und AOI,
- SIS-Wien-Index und SIS-Rohcaches,
- GRM2023-Raster-/Maskencaches.

Der 3.5-GB-Wien-Stream wurde für die lokale Untersuchung nur gelesen und nicht
ersetzt. Die beiden Minimalregressionen decken die bekannten Fehlergruppen
vollständig ab; ein neuer vollständiger Wien-Lauf bleibt die abschließende
End-to-End-Validierung des neu erzeugten Gesamtstreams und der nachfolgenden
Dissolve-/SIS-Prüfungen.
