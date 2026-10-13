# Wiener Gartenstraßen – Bestandsanalyse (Prototyp)

Ziel: Wiener Straßenabschnitte anhand ihrer tatsächlichen Grünflächen, Baumkronenüberschirmung und Nutzung des Straßenraums nachvollziehbar untersuchen. **Noch keine fertige Klassifikation von Gartenstraßen.**

## Schritt 1: FMZK-Verkehrsflächen testen

Die Stadt Wien bietet die FMZK sowohl als gesamtes GeoPackage als auch als einzelne WFS-Layer an. Für den ersten Test werden abgerufen:

- `ogdwien:FMZKVERKEHR1OGD`
- `ogdwien:FMZKVERKEHR2OGD`

Das Skript verwendet bewusst **WFS 1.0.0** mit EPSG:4326 (BBOX: Längengrad/Breitengrad), einen kleinen Standard-Ausschnitt im Übergangsbereich Wieden/Margareten sowie `maxFeatures=5000`. Wenn eine Rückgabe an die Grenze stößt, bricht es ab, statt einen unvollständigen Datensatz als vollständig auszugeben.

**Lokaler Aufruf (nur Python-Standardbibliothek erforderlich):**

```bash
python -m unittest discover -s tests -v
python scripts/fetch_fmzk.py
# Alternativ zusätzlich Shapefile-ZIPs:
python scripts/fetch_fmzk.py --format both
# Eigene kleine BBOX:
python scripts/fetch_fmzk.py --bbox 16.355,48.192,16.360,48.196
```

Ergebnis in `data/raw/` (nicht in Git versioniert): `fmzk_verkehr1.geojson`, `fmzk_verkehr2.geojson` und `manifest.json` mit Quelle, Datum, Anzahl, vorhandenen Feldern und `F_KLASSE`-Verteilung. Bei `--format both` entstehen zusätzlich Shapefile-ZIPs. GeoJSON ist für den späteren Analysecode unkomplizierter und vermeidet Feldnamenverkürzungen im Shapefile.

Ein Workflow unter **Actions → FMZK-WFS-Test → Run workflow** führt Tests und Datenabruf auf einem GitHub-Runner aus; bei Erfolg sind die Ergebnisse als herunterladbares Artifact verfügbar.

## Fachliche Einschränkungen

- WFS und Gesamt-GeoPackage stammen aus derselben **FMZK-Produktfamilie**, müssen aber bezüglich **Datenstand, Feature-Schema und Geometrie** noch miteinander verglichen werden. Identischer Stand ist nicht belegt.
- `Verkehr1` und `Verkehr2` allein reichen für die gesuchte **Grünfläche im Straßenraum** nicht aus. Als nächste Quelle sind `FMZKGRUEN1OGD` und `FMZKGRUEN2OGD` zu prüfen, ebenso die Abgrenzung öffentlicher Straßenflächen.
- Das `F_KLASSE`-Attribut beschreibt die [Bodennutzungsklassen der FMZK](https://www.wien.gv.at/pdf/ma41/fmzk-attribute-wertebereiche.pdf). „Unversiegelt“ ist dabei nicht notwendigerweise „begrünt“.
- Baumkronenüberschirmung benötigen wir gesondert aus einem tatsächlich auswertbaren Grünraummonitoring-Datensatz; Baumstandorte allein erlauben keine exakte Kronenflächenberechnung.
- Die erste WFS-Abfrage ist **kein Wien-weiter Downloadprozess**. Für ganz Wien sollen die bereitgestellten GeoPackages verwendet werden.
- Nutzung und Weitergabe nur mit Quellenangabe gemäß [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.de) (Datenquelle: Stadt Wien – data.wien.gv.at).

## Datenquellen

- [FMZK-Vektordaten / WFS – data.gv.at](https://www.data.gv.at/datasets/7cf0da04-1f77-4321-929e-78172c74aa0b?locale=de)
- [Geowebservices der Stadt Wien](https://digitales.wien.gv.at/open-data/geowebservices/)
- [FMZK – Daten beziehen](https://www.wien.gv.at/stadtplanung/flaechen-mehrzweckkarte-daten-beziehen)

## Nächste Schritte

1. Echte WFS-Rückgabe prüfen: CRS, Geometrien, Klassenzuordnung, fehlende oder abgeschnittene Features.
2. Grün1/Grün2 ergänzen und öffentliche Straßenflächen gegenüber angrenzenden Grünflächen abgrenzen.
3. 10–20 exemplarische Straßenabschnitte als Validierungsfälle festlegen.
4. Kennzahlen für Bodenbegrünung und Kronenüberschirmung **getrennt** berechnen.
5. Danach vollständige, reproduzierbare Wien-Pipeline entwerfen.
