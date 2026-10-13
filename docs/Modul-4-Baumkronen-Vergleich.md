# Modul 4: Baumkronen und Überschirmungsgrad – modulare Vergleichsstrecke

**Stand:** 13. Oktober 2026. **Status:** erste reproduzierbare Vektor- und Messmodule implementiert; **keine Aussage, welcher Ansatz die beste Genauigkeit hat**. Der erste echte lokale Lauf sowie die fachliche Sichtkontrolle stehen noch aus. Die Straßenraum-Abgrenzung aus Modul 2 und die Bodenbegrünung aus Modul 3 bleiben unverändert.

## Feste Schnittstellen

Modul 4 besteht aus voneinander unabhängigen Schritten:

1. **Quelladapter** beschaffen Daten und legen sie lokal unter `data/` ab.
2. **Kronen-Provider** erzeugen jeweils eine **GeoJSON-FeatureCollection aus Polygon/MultiPolygon in EPSG:4326**. Alle Quellenattribute dürfen unterschiedlich sein; nur die Geometrie ist verpflichtend.
3. **Überschirmungsmessung** erhält beliebige Kronen-Polygone plus das **Straßenraum-Polygon-GeoJSON** von Modul 2. Sie rechnet metrisch in EPSG:31256: `100 × Fläche(Vereinigung(Kronen) ∩ Vereinigung(Straßenraum)) / Fläche(Vereinigung(Straßenraum))`.
4. **Vergleichsmodul** berechnet pro Kronenquelle dieselbe Quote und zusätzlich paarweise **Kronenflächen-Überlappung (IoU)** und nur in einer Quelle vorhandene Flächen. **Eine hohe IoU ist keine gemessene Genauigkeit**, sondern nur eine Ähnlichkeit zweier Verfahren.

Kronen dürfen über Straßenflächen ragen, obwohl der Baumstamm **außerhalb** liegt. Überlappende Kronen werden in der Flächensumme nur **einmal** gezählt. Überschirmung wird **nicht zur Bodenbegrünung addiert**; die Ebenen können übereinander liegen.

## Vier zu prüfende Kronenquellen

| Ansatz | Datengrundlage | Geometriemodell / Aussage | Stand |
| --- | --- | --- | --- |
| **A – Wien Baumkataster** | Punktgeometrien und Attribut `KRONENDURCHMESSER` via WFS `ogdwien:BAUMKATOGD` | Kreis um Stammposition, Radius = halber Durchmesser; fachliche Näherung | **Vorbereitet/implementiert** |
| **B – Wien + OpenStreetMap** | Gleiche Baumkatasterdaten, dazu OSM `natural=tree` mit `diameter_crown` oder `crown_diameter` | Fehlende Bäume ergänzen, mögliche Dubletten behandeln; fehlende Durchmesser ausdrücklich markieren oder nur mit Opt-in schätzen | **Vorbereitet/implementiert** |
| **C – Grünraummonitoring 2023** | Rasterklassifikation der Stadt Wien; **50 cm Rasterauflösung**, **Baumschicht als Klasse 3**, Sommerbefliegungen 2023, Infrarot-True-Orthofotos und Laserscanning | Potenziell direkter, unabhängiger Kronennachweis auch auf privaten Grundstücken. Raster zu Polygondaten nur mit geprüfter Pixel-/Farb-Klassenübersetzung | **Datenquelle identifiziert; Import noch offen** |
| **D – BEV Orthofotos mit Infrarot** | BEV RGB/NIR bzw. IR-Darstellungen | Eigene Kronensegmentierung; nur NIR/NDVI allein trennt Bäume nicht sicher von Gras/Sträuchern, Höhe/Objektgrenzen benötigt | **Recherche, keine Implementierung** |

**Hinweis zu C:** Die Wiener OGD-Metadaten führen sowohl **Grünraummonitoring 2022** als auch **2023**; die 2023er Daten sind tatsächlich veröffentlicht. Die abgerufene WMS-Darstellung ist **kein garantierter kategorischer GeoTIFF-Rohdatenexport**. Vor der Automatisierung müssen wir die konkrete GetCapabilities-Ebene, den tatsächlich vorliegenden WMS-Rastertyp, NoData/Transparenz sowie die eindeutige Zuordnung zur **Baumschicht (3)** prüfen. Aus einer hübschen WMS-Kartenfarbe allein darf noch kein Kronenflächenwert abgeleitet werden.

**Hinweis zu B / Kartensammlung:** Der MapLibre/Maptoolkit-Code unter `Kartensammlung/src/app/overlays/providers/stadtplan-wien.js` verwendet `https://tiles.radlobby.at/Baumkataster/tilejson.json` mit `sourceLayer=baumkataster` und erkennt `KS_SOURCE=osm_tree` bzw. `osm_tree_row`. Die dort benutzten **Zoom-Pixelradien** sind für Kartenvisualisierung, **nicht** die metrischen Kronenradien der Messung. Die Herkunft des OSM-/Baumreihen-Imports ist im verlinkten Overlaycode sichtbar, die ursprüngliche Erzeugung des Tile-Datensatzes wurde nicht unabhängig geprüft.

## Jetzt implementierte Scripts

| Skript | Eigenständige Rolle |
| --- | --- |
| `scripts/fetch_vienna_trees.py` | Kleiner WFS-Abruf des Wiener Baumkatasters für die FMZK-Test-BBOX **plus 35 m Rand**; Cache und GeoJSON-Validierung, Schutz gegen maxFeatures-Abschneiden |
| `scripts/build_canopy_circles.py` | Kronenkreise aus **separaten lokalen GeoJSON**-Eingaben Wien/OSM; eigene Qualitäts- und Dublettenberichte |
| `scripts/measure_canopy_cover.py` | Universelle Kronen-Flächenmessung, **unabhängig vom Kronen-Provider**, identischer Straßenraumvertrag wie Modul 3 |
| `scripts/compare_canopy_methods.py` | Vergleicht 2+ Kronen-GeoJSONs auf identischem Straßenraum: Prozentsatz, IoU, Fläche nur A/nur B |

**Erster echter lokaler WFS-Abruf bestätigt (13.10.2026):** Der Wiener WFS hat **252 Baum-Punkte** geliefert (`wfs_heruntergeladen`) und die bestehende BBOX-/Koordinatenprüfung bestanden. Der nächste Schritt scheiterte zunächst ausschließlich an einer **zu restriktiven CRS-Prüfung** im Kronenkreis-Importer: Das alte GeoJSON-Format von WFS kann ein `crs`-Attribut enthalten, obwohl EPSG:4326 verwendet wird. Dieser Importfehler ist behoben: bekannte EPSG:4326-/CRS84-Deklarationen werden akzeptiert, andere Bezugssysteme weiterhin abgewiesen. **Der tatsächliche Kronenkreis- und Messlauf ist noch zu bestätigen**; die 252 Punkte sind die heruntergeladenen Baumstandorte, noch keine 252 fertigen Kronenpolygone. Die originale WFS-Datei bleibt unverändert im lokalen Cache.

## Erste Testreihe: Ansatz A

Voraussetzung: FMZK-Testausschnitt aus Modul 1 und `fmzk_strassenraum.geojson` aus Modul 2.


```bash
./scripts/update-and-sync.sh
.venv/bin/python -m scripts.fetch_vienna_trees  # nur bei fehlendem WFS-Cache nötig
.venv/bin/python -m scripts.build_canopy_circles --wien data/processed/baumkronen/baumkataster_wfs.geojson
.venv/bin/python -m scripts.measure_canopy_cover
```

**Nach dem erfolgreichen WFS-Download vom 13.10.2026:** Nach `./scripts/update-and-sync.sh` reichen die letzten **beiden** Befehle (`build_canopy_circles`, `measure_canopy_cover`); den Download nicht unnötig wiederholen. Falls weiterhin ein CRS-Fehler erscheint, die `crs`-Deklaration der WFS-Datei kontrollieren, statt das Attribut ohne Prüfung zu löschen.

Dateien:

- `data/processed/baumkronen/baumkataster_wfs.geojson` und `baumkataster_wfs_bericht.json`: rohe, lokal gespeicherte städtische Baum-Punkte.
- `data/processed/baumkronen/baumkronen_kreise.geojson` und `baumkronen_kreise_bericht.json`: erzeugte metrische Kronenkreise und Ausschluss-/Dublettenstatistik.
- `data/processed/ueberschirmung/ueberschirmung_bericht.json` und `ueberschirmte_flaeche.geojson`: **Überschirmungsgrad** und zur Sichtkontrolle an der Straßenmaske beschnittene Kronenunion.

Zunächst die Ergebnisse mit einem aktuellen Orthofoto und dem Baumkataster der Kartensammlung vergleichen. **Nicht bereits einen stadtweiten Prozentwert extrapolieren.**

## Zweite Testreihe: Ansatz B (OSM ergänzen)

Lokale OSM-Daten benötigen **GeoJSON-Punkte** für `natural=tree`. Sie können unabhängig bereitgestellt werden. Baumreihen `natural=tree_row` werden derzeit **bewusst nicht künstlich in Einzelbäume umgewandelt**; eine solche räumliche Approximation müsste separat geprüft werden.


```bash
# Wien-Only-Ausgabe für den Vergleich erhalten
.venv/bin/python -m scripts.build_canopy_circles \
	--wien data/processed/baumkronen/baumkataster_wfs.geojson \
	--out-dir data/processed/baumkronen/variante_wien

# OSM-Punkte mit realem Kronendurchmesser ergänzen
.venv/bin/python -m scripts.build_canopy_circles \
	--wien data/processed/baumkronen/baumkataster_wfs.geojson \
	--osm data/processed/baumkronen/osm_baeume.geojson \
	--out-dir data/processed/baumkronen/variante_kombiniert

# Dann beide Varianten gegen dieselbe Straßenraum-Maske vergleichen
.venv/bin/python -m scripts.compare_canopy_methods \
	--candidate wien=data/processed/baumkronen/variante_wien/baumkronen_kreise.geojson \
	--candidate kombiniert=data/processed/baumkronen/variante_kombiniert/baumkronen_kreise.geojson
```

**Regeln:** Bäume ohne verwertbaren Kronendurchmesser werden normalerweise **ausgelassen und gezählt**. Die bewusst nicht standardmäßig gewählte Option `--osm-default-diameter-m 5` führt dagegen eine eigene **geschätzte** Variante ein; im Bericht sichtbar markieren, nicht mit gemessenen Daten verwechseln. OSM-Punkte binnen **2 m** eines Wien-Punkts werden als **mögliche Dubletten** protokolliert und für die Kombivariante nicht doppelt gezählt. Das ist ein vorläufiger Näherungswert, kein garantierter identischer Baum; Ausschlüsse gezielt prüfen. Baumstämme auf privaten Grundstücken können dennoch Kronen über Straßen beitragen.

Die A/B-Gegenüberstellung ist zunächst nur möglich, wenn eine geeignete OSM-GeoJSON-Datei bereitgestellt wird. **Es gibt im Repo noch keinen fertig geprüften OSM-Downloaddienst.** Eine später angebotene kombinierte Tilequelle könnte dafür als eigener weiterer Quelladapter dienen, ohne das Messmodul zu verändern.

## Nächster Arbeitsschritt C: Grünraummonitoring 2023

1. Den **exakten WMS-Layernamen** und seine tatsächliche Ausgabe aus **GetCapabilities** ermitteln.
2. Im FMZK-Testausschnitt eine möglichst **verlustfreie oder kategorial eindeutige** Baumschicht-Maske herunterladen, **keine RGB/NIR-Darstellung ungeprüft zu Kronen umetikettieren**.
3. Pixel-/Raster-Weltkoordinaten und NoData vollständig dokumentieren. Die **Fläche** des Baumschicht-Rasters schneiden bzw. als Polygonmaske exportieren; keine künstliche Feingeometrie vorgaukeln (50-cm-Pixel).
4. Diese Maske in dasselbe **Kronen-Polygon-GeoJSON** überführen und in `scripts.compare_canopy_methods` gegen A und B vergleichen.

Erst **nach** der tatsächlichen Gegenprüfung von Geometrien, Aufnahmedaten und Randartefakten entscheiden, welchen Ansatz wir als Standard verwenden oder ob eigene BEV-NIR-Segmentierung sinnvoll ist.

## Langfristige Modularität

Alle Kronenprovider sollen dieselbe **Kronen-Geometrieschnittstelle v1** bedienen: GeoJSON FeatureCollection, Polygon/MultiPolygon, EPSG:4326; Attribute optional. Modul 4 (Messung) importiert keinen der Provider. Die Straßenraum-Eingabe bleibt die bereits in [Modulare Architektur](Modulare-Architektur.md) vereinbarte Schnittstelle von Modul 2.

Das Vergleichsmodul berichtet bewusst **Unterschiede**, nicht „der beste Ansatz“. Ohne unabhängige Referenzflächen (z. B. manuell geprüfte Kronenumrisse über Sommerorthofotos) kann kein Verfahren allein auf Basis einer größeren Überschirmungsquote als genauer bezeichnet werden. Beim Wechsel des Standardproviders und bei Änderungen an der Straßenraum-Maske Vergleichsversion und SHA-256 erhalten.

Quellinformationen: [Stadt Wien – Baumkataster](https://www.wien.gv.at/umwelt/stadtbaeume); [data.gv.at – Grünraummonitoring 2022](https://www.data.gv.at/datasets/684d2bbd-9bb7-319c-acb6-c1120e74e123?locale=de); [data.gv.at – OGD Update 09/2026](https://www.data.gv.at/ogd-update-wien-092026/); [BEV – Orthophoto Farbe](https://www.bev.gv.at/Services/Produkte/Luftbildprodukte/Orthophoto-Farbe.html).
