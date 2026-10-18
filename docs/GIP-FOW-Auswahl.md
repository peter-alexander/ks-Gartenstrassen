# GIP-FOW-Auswahl für Gartenstraßen

Quelle: vom Projekt bereitgestellte `lut_form_of_way_202607081451.csv`
(67 gültige oder unbekannte FORM_OF_WAY-Codes, Stand der gelieferten LUT).
Technische Definition: `scripts/gartenstrassen_fow.py`.

## Positive Auswahl statt Wortsuche

| Verwendung | Codes | Bedeutung |
|---|---|---|
| Eigenständige Gartenstraßen-Kandidaten; im SIS-V2-PMTiles | **2, 3, 14** | Fahrbahnteilung (keine Autobahn), ungeteilte Fahrbahn, Fußgängerzone |
| Nur als **begleitende** Kante bei 20-m-Parallelprüfung | **15, 504, 505** | Fußweg, Geh- und Radweg, Radweg |
| In keiner dieser beiden Ausgaben | **alle anderen**, auch NULL, unbekannt und zukünftige Codes | Keine automatisch geeignete Straßenachse |

Nur Paare mit **mindestens einer Hauptkanten-FOW 2, 3 oder 14** werden
bei der Parallelprüfung akzeptiert. Zwei Radwege oder Fußwege ohne
begleitende Fahrbahn bzw. Fußgängerzone ergeben daher keine eigene
Gartenstraßen-Gruppe. Die 20-m-Suche bleibt räumlich und fachlich vorläufig.

Die Typen mit eingeschränktem Zugang (z. B. 20 Straße nur für Berechtigte),
Kreisverkehr (4), Ab-/Einbiegefahrbahnen (10),
Parkplatz-/Garagen- und Sonderzufahrten (6, 7, 11, 12, 17),
unstrukturierte Kreuzungen (8), Wege *im Objekt* (13, 16, 21, 23, 25, 26),
Furt (19), Stiegen/Steige (18, 21, 401–403),
Aufzüge/Rolltreppen (22–25, 523),
Bahn/Schiene/Monorail/Straßenbahn (101–103, 506–515),
weitere Seilbahnen und Lifte (516–528),
Wasserwege (601), MTB-/Alpin-/Gletscherwege (200, 220, 404–406),
Autobahn (1) sowie alle sonstigen Spezialtypen sind ausgeschlossen.

Vollständige Ausschlusscodes der gelieferten LUT (nur für diese beiden Ausgaben):

`-1, 1, 4, 6, 7, 8, 10, 11, 12, 13, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 101, 102, 103, 200, 220, 301, 400, 401, 402, 403, 404, 405, 406, 506, 507, 508, 509, 510, 511, 512, 513, 514, 515, 516, 517, 518, 519, 520, 521, 522, 523, 524, 525, 526, 527, 528, 599, 601, 701, 702`.

## Geltungsbereich

- **Parallelkantenanalyse**: Unerwünschte FOWs werden bereits beim
  Lesen des GIP-Indexes ausgeschlossen; sie gelangen nicht in das
  GeoJSON der Kandidatenpaare. Im Diagnose-JSON sind Gesamtzahl,
  berücksichtigte und ausgeschlossene Achsenzahl protokolliert.
- **SIS-V2-PMTiles**: Nur 2, 3 und 14 sowie der bestehende
  Mindestflächenfilter (100 m²) werden veröffentlicht. Der
  PMTiles-Bericht enthält FOW-Ausschlusszahlen nach Code.
- **V0-PMTiles**: Der bereits existierende V0-Export akzeptiert
  ausschließlich FOW=3 und wird nicht umgedeutet.
- **Originaldaten, GIP2-Index, Voronoi-Partition und die vollständigen
  SIS-V2-Mess- und QA-Dateien** bleiben unverändert. Die FOW-Liste
  ist ein vorsichtiger Veröffentlichungs- und Kandidatenfilter,
  keine allgemeine Landnutzungsbewertung.

## Bereits bestehendes PMTiles aktualisieren

~~~bash
git pull --ff-only
SIS_V2_ROOT="$PWD/data/wien/analysis/wien" \
	bash scripts/run-sis-v2-pilot.sh --from pmtiles --until pmtiles
~~~

Diese Phase startet **keine** Neuberechnung von SIS, GIP, GRM,
Voronoi oder Begrünungsmessungen. Sie liest die vorhandene
`ergebnisse/gip_abschnitte.geojson`, filtert FOW und Fläche und
ersetzt das bestehende `gartenstrassen_sis_v2.pmtiles` **erst nach
erfolgreichem Neubau** atomar. Bei Fehlern bleibt das alte Archiv stehen.
Der PMTiles-Lauf kann bei sehr großen GeoJSON-Dateien erhöhten
Arbeitsspeicher für die Filtervorstufe benötigen.

Der Standort der vorhandenen Daten muss vorher durch die
[Wien-Datenmigration](Wien-Datenumzug.md) verifiziert sein.
