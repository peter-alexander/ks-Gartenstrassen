# Wiener Gartenstraßen – datenbasierte Bestandsanalyse

## Methodik des ersten Wien-Durchgangs (Oktober 2026)

Ziel ist die flächendeckende, quantitative Beschreibung von **Bodenbegrünung** und
**Baumkronenüberschirmung** im Wiener Straßenraum als Grundlage für die
explorative Identifikation bestehender Straßen mit Gartenstraßen-Potenzial.

1. **Straßenraumabgrenzung:** Aus der **Flächenmehrzweckkarte (FMZK)** der Stadt Wien
   wurden die Verkehrsflächenklassen 21, 23, 24, 25, 33 und 39 als Straßenraumkern
   abgeleitet. Weitere FMZK-Flächen wurden mithilfe der Grundstücks- (`gst`) und
   Nutzungsflächeninformationen (`nfl`) des **BEV-Katasters** räumlich beurteilt.
   Für eine zusätzliche Zuordnung sind insbesondere eine Deckung von mindestens
   95 % durch Kataster-Verkehrsnutzungen 95/65 und höchstens 5 % durch andere
   Nutzungen erforderlich. Die resultierende Straßenraummaske ist eine
   **vorläufige GIS-Abgrenzung**, keine rechtliche Feststellung öffentlichen Straßenraums.
2. **Straßenabschnitte:** Die Straßenraummaske wurde anhand des amtlichen
   **GIP-Straßengraphen** (reguläre Achsen, FOW = 3) mittels metrischer
   Voronoi-Partitionierung einzelnen Straßenabschnitten zugewiesen.
   Kreuzungsbereiche, Sonderachsen und nicht zuordenbare Restflächen werden
   gesondert bilanziert und nicht in die Abschnittsquoten einbezogen.
3. **Bodenbegrünung:** Die FMZK-Grünflächenklassen **58 und 69** wurden
   geometrisch vereinigt, mit den Abschnittspolygonen verschnitten und als
   prozentueller Anteil an der jeweils zugeordneten Abschnittsfläche berechnet.
   Die Vereinigung verhindert eine Doppelzählung überlappender Grünflächenklassen.
4. **Baumkronenüberschirmung:** Die Baumschicht des Wiener
   **Grünraummonitorings 2023 (GRM2023)** wurde aus einem gerenderten WMS
   mit **0,5 m Pixelauflösung** abgeleitet, in Flächen umgesetzt und mit denselben
   Abschnittspolygonen verschnitten. Der resultierende Anteil bezeichnet
   die Baumkronenüberschirmung der jeweiligen Abschnittsfläche.
   Das WMS-Bild ist keine amtliche Rohpolygongeometrie.
5. **Visualisierung:** Die beiden gemessenen Prozentwerte werden getrennt
   dargestellt. **40 % Bodenbegrünung** bzw. **60 % Kronenüberschirmung**
   bilden jeweils das obere Referenzniveau der Farbskala (grün/100 % der
   Darstellungsnormierung). Diese Bezugswerte sind **kartografische
   Vergleichsmaßstäbe**, keine empirisch validierten Gartenstraßen-Grenzwerte.
   Boden- und Kronenanteile dürfen wegen räumlicher Überlagerung
   nicht zu einer Gesamtbegrünungsfläche addiert werden.

**Geplante Weiterentwicklung:** In weiteren Wien-Versionen soll die
Kronenüberschirmung alternativ (a) aus dem Wiener **Baumkataster**,
(b) aus dem **um OpenStreetMap-Bäume ergänzten Baumkataster** und
(c) aus einer eigenständigen fernerkundlichen Klassifikation anhand
von **Infrarot-Luftbildern**, digitalem Geländemodell (**DGM/DTM**)
und digitalem Oberflächenmodell (**DOM/DSM**) bestimmt werden.
Für Baumstandortdaten sind Kronendurchmesser bzw. nachvollziehbare
Schätzmodelle nötig; bei Luftbildern sollen Vegetationssignale und
Höheninformationen zur Unterscheidung von Kronen und bodennaher Vegetation
kombiniert werden. Die Ergebnisse sollen bei **identischen Straßenabschnitten**
methodisch verglichen und anhand geeigneter Referenzflächen überprüft werden.
Frühere Pilotversuche zu diesen Alternativen sind unter
[Modul 4 – Baumkronen-Vergleich](docs/Modul-4-Baumkronen-Vergleich.md) dokumentiert.

## SIS-basierte V2 (Entwicklungsbranch, Oktober 2026)

Für die Weiterentwicklung nach dem Feedback zur Straßenraumabgrenzung
steht ein **vollständig getrennter SIS-Pilotpfad** zur Verfügung.
Die Straßenflächen werden darin ausschließlich aus SIS-Belagsflächen
abgeleitet, nicht mehr aus FMZK und Kataster. GIP-Abschnitte werden
erneut auf diesen SIS-Flächen partitioniert, Bodenkennzahlen aus SIS-BELAG
und Baumkronen weiterhin aus GRM2023 berechnet. Eine eigene QA,
CSV/GeoJSON und PMTiles-Ausgabe sind vorbereitet.

Der erste vollständige SIS-Testlauf wurde am 17. Oktober 2026 technisch
erfolgreich bis zum PMTiles abgeschlossen; die fachliche Sichtprüfung und
Freigabe stehen noch aus. Die Regel ist BL/ST/WI = begrünt, alle übrigen
BELAG = nicht begrünt; die V2-Voronoi-Aufteilung schließt Kreuzungen vorerst nicht aus. Die hier
darunter dokumentierten V0-Kennzahlen bleiben historisch und werden
durch die neue Methodik nicht rückwirkend umgedeutet.

Ausführung und fachliche Einschränkungen:
[**SIS-Belagsflächen – V2-Pilot**](docs/SIS-Belagsflaechen-V2-Pilot.md).

## Stand und Ergebnisse

Der **erste vollständige Wien-Durchgang** ist erfolgreich abgeschlossen
(16. Oktober 2026). Flächenberechnungen erfolgten in **EPSG:31256**;
die für die Kartendarstellung exportierten Geometrien liegen in **EPSG:4326**.

| Größe | Ergebnis |
| --- | ---: |
| Ausgewertete reguläre GIP-Abschnitte | 24.937 |
| Zur Darstellung ausgewählte Abschnitte (≥ 100 m² je GIP-ID) | 24.306 |
| Durch den Darstellungsfilter ausgeschlossene Abschnitte | 631 |
| Fläche der exportierten Abschnitte | ca. 36,274 km² |
| Protokollierte, kontrollierte WGS84-Exportkorrekturen | 226 |

Der Flächenfilter **ab 100 m²** gilt ausschließlich für die
Veröffentlichung; die vollständigen metrischen Ergebnisse bleiben erhalten.
Die GIP-Zuordnung ist eine **V0-Methodik**: Der erfolgreiche technische
Gesamtlauf belegt noch keine unabhängige fachliche Validierung jeder
einzelnen Straßenraumgrenze oder Baumkrone.

## Ergebnisse ansehen und verwenden

**Die Geodaten liegen nicht in diesem Git-Repository.** Das Verzeichnis
`data/` ist absichtlich ignoriert; der Code, die Prüfungen und die
Verfahrensbeschreibung sind hier versioniert. Wer bereits die exportierten
Ergebnisdateien besitzt, kann sie folgendermaßen nutzen:

| Datei | Verwendung |
| --- | --- |
| `veroeffentlichung_100m2/gip_abschnitte.geojson` | GIP-Abschnittspolygone samt Boden- und Kronenwerten; in GIS-Software oder einen GeoJSON-Importer laden |
| `veroeffentlichung_100m2/gip_abschnitte.csv` | Tabellenanalyse und Join über `gip_id` |
| `veroeffentlichung_100m2/gartenstrassen_wien.pmtiles` | Kompakte **Vektorkachel-Darstellung** (Zoom 8–17) in PMTiles-fähigen Kartenanwendungen |
| `veroeffentlichung_100m2/export_bericht.json` und `pmtiles_bericht.json` | Datenherkunft, Prüfsummen, Ausgabeparameter und Export-QA |
| `begruenung_grm/gip_abschnitte_begruenung.gpkg` | Vollständige metrische QA-Daten einschließlich der nicht veröffentlichten Teilflächen |

Alle relativen Dateinamen in dieser Tabelle beziehen sich auf
`data/processed/wienweit/wien/`.

Die wichtigsten Attribute sind `gip_id`, `strassenname`,
`abschnitt_flaeche_m2`, `boden_m2`, `boden_pct`,
`grm_kronen_m2` und `grm_kronen_pct`.
`NULL` bei Kronenwerten bedeutet **fehlende Information**, nicht
0 % Überschirmung.

**Hinweis zu PMTiles:** Vektorkacheln sind zur **Visualisierung**, nicht
zur genauen Flächenmessung bestimmt. Sie enthalten je Zoomstufe
quantisierte und an Kachelgrenzen geschnittene Geometrien.
Beim Webhosting müssen HTTP-Range-Anfragen unterstützt werden.
Für die Flächenanalyse die CSV bzw. die metrischen GeoPackage-Daten verwenden.

## Selbst reproduzieren

Benötigt werden Linux/WSL, Python, GDAL (`ogr2ogr`), die vollständige
lokale **FMZK-WIEN-GeoPackage-Quelle** und Zugriff auf die
jeweiligen BEV-, GIP- und GRM2023-Dienste. Der Lauf benötigt
ausreichend Speicherplatz für die stadtweiten Kachel-Caches.

```bash
git clone https://github.com/peter-alexander/ks-Gartenstrassen.git
cd ks-Gartenstrassen
sudo apt install gdal-bin
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-analysis.txt

# Quell-GPKG vorab lokal unter data/raw/FMZK_WIEN_GP.gpkg ablegen.
# Schrittweiser, wiederaufnehmbarer Wien-Lauf:
bash scripts/run-wien-gartenstrassen.sh --until grid
bash scripts/run-wien-gartenstrassen.sh --from gip-fetch --until export
```

Der Lauf ist in Phasen unterteilt und prüft Zwischenergebnisse.
Bestehende vollständige Ergebnisse werden nicht ungefragt überschrieben.
Mit `--fmzk /voller/pfad/FMZK_WIEN_GP.gpkg` kann eine andere
Quelldatei angegeben werden. Parameter, Datenbezug, Caches und
Fehlerbehandlung erläutert der [Wienweite Gesamtlauf](docs/Wien-Gesamtlauf.md).

Für die **reine Neuerstellung der PMTiles** aus einem bereits
vorhandenen Export wird zusätzlich
[Felt/Tippecanoe](https://github.com/felt/tippecanoe) ≥ 2.17 benötigt:

```bash
.venv/bin/python -m scripts.build_wien_pmtiles --replace
```

Der Befehl erzeugt `gartenstrassen_wien.pmtiles` mit
**Minzoom 8 / Maxzoom 17**, überschreibt eine vorhandene Version erst
nach erfolgreich abgeschlossenem Build und legt **keine Sicherungskopie**
der bisherigen PMTiles-Datei an. Das Original-GeoJSON bleibt unverändert.

## Tests, Dokumentation und Entwicklung

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Der Code wird auch in [GitHub Actions](https://github.com/peter-alexander/ks-Gartenstrassen/actions/workflows/tests.yml)
offline getestet. Reale Quell- und Gesamtläufe müssen mit den
lokal verfügbaren Geodaten überprüft werden.

Die weiterführende Dokumentation ist nach Themen getrennt:

- [Modulare Architektur und Datenschnittstellen](docs/Modulare-Architektur.md)
- [Straßenraumabgrenzung mit FMZK und Kataster](docs/Methodik-Strassenraum-FMZK-Kataster.md)
- [Baumkronen-Methoden und Variantenvergleich](docs/Modul-4-Baumkronen-Vergleich.md)
- [GIP-Straßenabschnitte und Flächenzuordnung](docs/Modul-5-Strassenabschnitte.md)
- [Abschnittsbezogene Begrünungskennzahlen](docs/Modul-6-Abschnittskennzahlen.md)
- [Wienweiter Gesamtlauf, Qualitätssicherung und Fehlerdiagnosen](docs/Wien-Gesamtlauf.md)
- [Historischer README-Stand und frühe Entwicklungsprotokolle](docs/history/README-bis-2026-10-16.md)

Für zukünftige Methodenänderungen sollen die jeweiligen Versionen auf
denselben Referenzabschnitten verglichen, Prüfabweichungen dokumentiert
und nicht durch stillschweigende Toleranzerhöhungen verdeckt werden.

## Datenquellen und Hinweise

Grundlage sind Daten der **Stadt Wien** (FMZK und GRM2023),
des **BEV** (Kataster) und der **GIP** (Straßengraph).
Die Quellen- und Lizenzbedingungen der jeweiligen Datensätze
einschließlich erforderlicher Quellenangaben sind bei einer
Weitergabe der Ergebnisse zu beachten.
Für die Stadt-Wien-OGD-Daten siehe [data.wien.gv.at](https://data.wien.gv.at/)
und die dort angegebenen Nutzungsbedingungen.
