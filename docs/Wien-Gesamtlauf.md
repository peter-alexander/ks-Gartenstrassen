# Wienweiter Gartenstraßenlauf – ausführbarer Ablauf

**Stand 15.10.2026:** Der Alsergrund-Pilot mit 586 eindeutigen FOW=3-GIP-Abschnitten und Boden-/GRM2023-Messung wurde lokal erfolgreich ausgeführt. **Ein vollständiger Wien-Lauf wurde noch nicht ausgeführt**; Zeitbedarf, Datenvolumen und technische Vollständigkeit sind daher nicht behauptbar.

Die Berechnung verwendet weiterhin die vorhandenen Module. Neu sind der phasenweise Treiber **scripts/run-wien-gartenstrassen.sh** und der reine Ergebnisexport **scripts/wienwide_result_export.py**. Die vereinbarten **100 m²** gelten ausschließlich für den regulären Export, nicht für die Quellverarbeitung, die Voronoi-Aufteilung oder die QA-Bilanz.

## Voraussetzungen

- Das vollständige lokale Original **FMZK_WIEN_GP.gpkg** in EPSG:31256.
- Die Python-Venv mit **requirements-analysis.txt** und GDAL-CLI (ogr2ogr).
- Abrufbarkeit der MA41-AOI, GIP-WFS-, BEV-Kataster- und GRM2023-WMS-Quellen. Bestehende geprüfte Kachel-Caches bleiben erhalten.
- Genügend lokaler Speicher für Eingangs-, Zwischen- und vollständige QA-Ergebnisdateien. Es gibt noch keinen real gemessenen Wien-Benchmark.

## Start

~~~bash
git pull --ff-only

# Komplett, mit Fehlerstopps und wiederverwendbaren Caches:
bash scripts/run-wien-gartenstrassen.sh

# FMZK liegt außerhalb des vorgeschlagenen data/raw/-Pfades:
bash scripts/run-wien-gartenstrassen.sh \
	--fmzk /absoluter/pfad/FMZK_WIEN_GP.gpkg
~~~

Für den **ersten Wien-Lauf** empfehlen sich kontrollierte Etappen:

~~~bash
# Amtliche Wien-AOI (alle 23 Bezirke) und festes 1-km-Raster.
bash scripts/run-wien-gartenstrassen.sh --until grid

# GIP-WFS-Caches vollständig aufbauen, dann globalen Index.
bash scripts/run-wien-gartenstrassen.sh --from gip-fetch --until gip-index

# FMZK-/Kataster-Eingaben und metrische Straßenraumkacheln.
bash scripts/run-wien-gartenstrassen.sh --from inputs --until street

# GIP-V0 und vierlagiges QA-GeoPackage.
bash scripts/run-wien-gartenstrassen.sh --from partition --until qa

# Gerenderte GRM2023-Baumschicht vollständig laden und prüfen.
bash scripts/run-wien-gartenstrassen.sh --from grm-fetch --until grm-build

# Boden-/Kronenmessung, reguläre Ausgabe und Benchmark.
bash scripts/run-wien-gartenstrassen.sh --from measure --until benchmark
~~~

**--from** und **--until** begrenzen die **ausgeführten Schritte**, nicht den geografischen Untersuchungsraum. Nach einem Abbruch kann die betroffene Phase wiederholt werden; bestehende vollständige Gesamtdateien werden nicht überschrieben. Geänderte Quellhashes, unvollständige Caches oder unzulässige Geometrien sind zu prüfen, nicht stillschweigend zu ignorieren.

## Pfade und Parameter

| Element | Standard |
| --- | --- |
| AOI | data/raw/bezirke-wien/wien.geojson |
| FMZK | data/raw/FMZK_WIEN_GP.gpkg |
| Analyse | data/processed/wienweit/wien/ |
| Raster | 1000 m, Halo 75 m |
| GIP-V0 | Stützpunkte 5 m, Knotenradius 7 m, maximaler Achsabstand 25 m, regulär FOW=3 |
| Kataster | 1500 Grundstücke je Analyse-Kachel als technisches Schutzlimit |
| GRM-GetMap | 0,5 s Pause zwischen neuen Abrufen |
| Ergebnisfilter | Globale GIP-Abschnittsfläche ab 100 m² |

**Vollständige Auswertung, unverändert und ohne Mindestflächenfilter:**

data/processed/wienweit/wien/begruenung_grm/

- **gip_abschnitte_begruenung.csv:** vollständige Kennzahlen aller GIP-IDs.
- **gip_abschnitte_begruenung.gpkg:** vollständiges QA-GeoPackage mit allen Teilflächen, Knotenbereichen, Sonderachsen und Restflächen.
- **begruenung_bericht.json:** Messbilanz und Provenienz.

**Reguläre Veröffentlichung, Mindestfläche 100 m²:**

data/processed/wienweit/wien/veroeffentlichung_100m2/

- **gip_abschnitte.csv:** gefilterte globale Abschnittszeilen.
- **gip_abschnitte.geojson:** genau ein in EPSG:31256 vereinigtes und anschließend nach EPSG:4326 transformiertes Feature pro ausgewählter GIP-ID. Attribute einschließlich **boden_pct** und **grm_kronen_pct** entsprechen den vollständigen Messungen.
- **export_bericht.json:** Quell-SHAs, vollständige/ausgegebene/ausgelassene GIP-IDs und Flächensummen.

Ein Abschnitt aus zwei Kachelfragmenten zu je 60 m² wird insgesamt als 120 m² berücksichtigt und **nicht** aussortiert. Eine eigenständige GIP-ID unter 100 m² erscheint dagegen nicht im regulären Ergebnis; ihre Geometrie und ihre Kennzahlen bleiben in den vollständigen QA-Daten erhalten. Der Export führt **keine Mittelung der Prozentwerte** durch.

Die **gip_abschnitte.geojson** kann nach erfolgreicher Sichtkontrolle in die Kartensammlung als **/Maps/gip_abschnitte.geojson** übernommen werden. Vorher Größe und Ladezeit testen; eine große ungekachelte GeoJSON ist nicht notwendigerweise das endgültige Auslieferungsformat.

## QA und fachliche Grenzen

1. Vollständige Kachelanzahl, geometrietopologische Straßenraumbilanz und Quell-SHAs müssen geprüft sein.
2. Sonderachsen mit FOW ungleich 3, Kreuzungsbereiche und Restflächen bleiben außerhalb der derzeitigen **regulären** GIP-Abschnittsquote, jedoch in der Gesamtbilanz.
3. Bodenbegrünung beruht auf der geometrisch vereinigten FMZK 58/69; GRM2023 ist eine **gerenderte WMS-Baumschicht**. Die beiden Anteile dürfen nicht addiert werden.
4. Der Kachel-Cache bietet technische Prüfsummen, aber bei langem GIP-WFS-Abruf **keine Garantie eines zeitlich konsistenten amtlichen Snapshots**.
5. Ein erfolgreicher Wien-Lauf ersetzt keine Ortsprüfung in QGIS/Kartensammlung, vor allem an großen Kreuzungen, Sonderachsen, Kachelgrenzen und Abschnitten mit extremen Prozentwerten.
6. Keine automatische Klassifikation als Gartenstraße und keine MBTiles-Ausgabe in dieser Phase.

## Regressionstests

~~~bash
.venv/bin/python -m unittest discover \
	-s tests -p 'test_wienwide_result_export.py' -v
~~~

Die Tests prüfen den Filter auf vollständige GIP-IDs statt auf Kachelfragmente, NULL-Kronenwerte sowie Abbruch bei widersprüchlichen Flächen.
