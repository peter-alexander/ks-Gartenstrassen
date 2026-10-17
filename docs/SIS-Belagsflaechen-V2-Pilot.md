# SIS-Belagsflächen – V2-Pilot (17.10.2026)

## Eingabe

Der erste Test verwendet **exakt** die bereits vorhandene Testdatei:

`https://tiles.radlobby.at/Gehsteigbreiten/Testdaten/SISBELAGOGD.json`

Sie ist nur ein Ausschnitt und ausdrücklich **kein vollständiger Wien-Datensatz**.
Die Testdatei kann automatisch einmal geladen oder unter `--source-file`
lokal übergeben werden. Es erfolgen keine neuen WFS-Anfragen für diesen Test.
Es werden **alle** `TYPE`-Klassen übernommen; die für Gehsteigbreiten
verwendete Filterung auf GG/EE/HH wird hier **nicht** angewandt.

## Ausführen

~~~bash
# Python-Umgebung laut README vorbereiten.
.venv/bin/python -m scripts.sis_belagsflaechen

# Alternativ, falls die Datei bereits lokal vorliegt:
.venv/bin/python -m scripts.sis_belagsflaechen \
	--source-file /pfad/SISBELAGOGD.json \
	--out-dir data/processed/sis-pilot-v2

# Offline-Tests:
.venv/bin/python -m unittest tests.test_sis_belagsflaechen -v
~~~

## Ausgabe und Sicherheitsregeln

- `SISBELAGOGD.json`: unveränderte Kopie der Eingabe.
- `sis.sqlite`: alle Einzelpolygone in EPSG:31256, Klasse `TYPE`,
  RTree-Index für Teilflächenabfragen, dazu `street` als geometrische
  Vereinigung aller Belagsflächen **ohne** Kreuzungsabzug.
- `bericht.json`: SHA-256, Featurezahl, Klassenhäufigkeiten,
  Summen-/Vereinigungsflächen, Überlappungsdifferenz.
- Bestehende Ergebnisordner werden nicht überschrieben.
- Ungültige Polygone, fehlendes `TYPE`, unpassende Koordinaten oder
  ein widersprüchliches CRS führen zum Abbruch, nicht zu stillen Reparaturen.

## Durchgängige SIS-V2-Pipeline

Die gesamte V2-Auswertung ist jetzt über einen eigenständigen Treiber
erreichbar; keine FMZK-/BEV-Katastereingaben nötig:

~~~bash
bash scripts/run-sis-v2-pilot.sh
~~~

Optional eine bereits vorhandene Testdatei übergeben:

~~~bash
SIS_V2_SOURCE=/pfad/SISBELAGOGD.json bash scripts/run-sis-v2-pilot.sh
~~~

Der neue Pilot bleibt vollständig getrennt von V0 unter
`data/processed/sis-v2-run/`. Das Pilot-AOI wird aus dem metrischen
Umgrenzungsrechteck der SIS-Testdatei erzeugt, mit 250-m-Arbeitskacheln
und 75-m-Halo. Die GIP-Daten und GRM2023-Baumschicht werden über die
bestehenden, quellengeprüften Abrufmodule für dieses Gebiet bezogen.
`--from` und `--until` erlauben einzelne Phasen. Mit `--no-grm`
kann die Kronenberechnung zunächst ausgelassen werden; in diesem Fall
bleiben Kronenwerte im Ergebnis `null`.

V2-Ausgaben:

- `qa.gpkg`: vollständige GIP-Partition inkl. Kreuzungskreise,
  Sonderachsen und Restflächen, unveränderte geometrische QA.
- `ergebnisse/gip_abschnitte.csv` und `.geojson`: GIP-Abschnitte,
  SIS-Bodenkennzahlen sowie optional GRM2023-Überschirmung.
- `ergebnisse/bericht.json`: Herkunft und Bilanz sowie
  die tatsächlich verwendeten Klassifikationsregeln.
- `gartenstrassen_sis_v2.pmtiles`: separate Publikationskacheln,
  GIP-Abschnitte ab 100 m², Zoom 8 bis 17; benötigt `tippecanoe`.

Die bisherigen Modul-3/6-FMZK-Quellspalten werden **nicht** mit
SIS-Werten umetikettiert. Stattdessen gelten ausdrücklich neue Felder:
`sis_vegetation_m2`, `sis_vegetation_pct`,
`sis_potentiell_unversiegelt_m2` und
`sis_potentiell_unversiegelt_pct`.

**Vorläufige Arbeitsklassifikation der Belagsarten (noch fachlich zu prüfen):**
Die Codes beziehen sich auf das Feld **BELAG**, nicht **TYPE**.
Vegetation: BL, ST, WI; potenziell unversiegelt: BL, ST, WI, KB, MW, GO.
Insbesondere KB (kein Belag), MW (wassergebundener Makadam) und GO
(Großsteinpflaster ohne Fugenverguss) dürfen **nicht** ohne Validierung
als tatsächlich entsiegelt oder begrünt interpretiert werden.
Der Begriff „potenziell unversiegelt“ ist daher absichtlich vorsichtig.
Diese Zuordnung muss am Originaldatensatz und anhand der amtlichen
Felddefinitionen fachlich geprüft werden.

Die V2-Zuordnung verwendet auf ausdrücklichen Wunsch zunächst ausschließlich
Voronoi-Flächen ohne Abzug von Kreuzungskreisen. V0 bleibt unverändert. Es gab
bislang **keinen echten Durchlauf** mit der angegebenen SIS-Datei
und keinen bestätigten GRM/GIP-Pilotdatenlauf.

## Noch offen / nächster Validierungsschritt



1. Die Testdatei später durch einen **gekachelten amtlichen WFS-Abruf**
   von `ogdwien:SISBELAGOGD` ersetzen. IDs, Dubletten,
   Abfragegrenzen und Vollständigkeit prüfen.
2. SIS-`TYPE`-Klassifikation gegen amtliche Definitionen und die
   tatsächlich im Pilot vorkommenden Kategorien bestätigen.
3. Kreuzungsplateaus erst nach fachlicher GIP-Prüfung abgrenzen;
   V2 enthält vorerst ausdrücklich **keinen** Kreuzungsausschluss.
4. Realtest der gesamten Kette und visuelle GIS-Prüfung; Ausgabe
   erst nach nachvollziehbarer QA für die Kartensammlung freigeben.
