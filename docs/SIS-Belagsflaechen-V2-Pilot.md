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

## Nächste Schritte / bewusst noch nicht umgesetzt

1. Die Testdatei durch **gekachelten amtlichen WFS-Abruf** von
   `ogdwien:SISBELAGOGD` austauschbar ersetzen. Vor einer Wien-Auswertung
   müssen Pagination, Anfragegrenzen, IDs, Dubletten, Kachelvollständigkeit
   und ggf. Feature-Grenzfälle geprüft sein.
2. Die metrische SIS-Union über einen **expliziten neuen V2-Pipeline-Eingang**
   an GIP-Partitionierung, GRM2023 und Ergebnisausgabe anbinden;
   V0-Straßenkacheln dürfen keinesfalls gemischt oder überschrieben werden.
3. Kreuzungsflächen erst nach fachlicher Prüfung der verfügbaren GIP-Daten
   definieren. Die aktuell verwendete 7-m-V0-Kreuzungsregel bleibt unverändert.
4. Entsiegelung/Bodenbegrünung anhand einer fachlich geprüften Zuordnung
   **aller relevanten SIS-TYPE-Werte** berechnen. Unbefestigte Bauflächen
   dürfen nicht automatisch als begrünte Fläche gelten.

Diese erste Implementierung liefert den reproduzierbaren Quell- und
Geometrie-Pilot, **noch keine fertigen Gartenstraßenkennzahlen**.
