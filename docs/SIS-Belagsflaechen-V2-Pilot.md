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

Die Flächen werden binär klassifiziert: **BELAG BL, ST oder WI = Bodenbegrünung**;
alle übrigen BELAG-Codes = nicht begrünt. Sämtliche TYPE-Klassen,
einschließlich Mauern (M1/M2), gehören zur gesamten SIS-Fläche.
Ausgabefelder: `boden_m2`, `boden_pct`, `nicht_begruent_m2`,
`nicht_begruent_pct`. Der Nenner ist die komplette SIS-Voronoi-Abschnittsfläche.

**Qualitätssicherung:** Die Summe der metrischen SIS-Polygonflächen darf
nur innerhalb numerischer Toleranz von ihrer Vereinigung abweichen.
Überlappungen führen zu einem Abbruch statt einer stillen Klassifikationsregel.

Die V2-Zuordnung verwendet auf ausdrücklichen Wunsch zunächst ausschließlich
Voronoi-Flächen ohne Abzug von Kreuzungskreisen. V0 bleibt unverändert. Es gab
bislang **keinen echten Durchlauf** mit der angegebenen SIS-Datei
und keinen bestätigten GRM/GIP-Pilotdatenlauf.

## Noch offen / nächster Validierungsschritt



1. Die Testdatei später durch einen **gekachelten amtlichen WFS-Abruf**
   von `ogdwien:SISBELAGOGD` ersetzen. IDs, Dubletten,
   Abfragegrenzen und Vollständigkeit prüfen.
2. Die binäre BELAG-Klassifikation (`BL`, `ST`, `WI` gegenüber allen
   anderen Klassen) und die vollständige Flächenbilanz am Pilot prüfen.
3. Kreuzungsplateaus erst nach fachlicher GIP-Prüfung abgrenzen;
   V2 enthält vorerst ausdrücklich **keinen** Kreuzungsausschluss.
4. Realtest der gesamten Kette und visuelle GIS-Prüfung; Ausgabe
   erst nach nachvollziehbarer QA für die Kartensammlung freigeben.
