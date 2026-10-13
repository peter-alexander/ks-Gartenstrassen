# Modulare Architektur – Wiener Gartenstraßen

**Stand 13.10.2026.** Das Projekt wird in unabhängigen Verarbeitungsschritten aufgebaut. Insbesondere darf der Austausch der Straßenraum-Abgrenzung **keine Änderung an den Kennzahlenmodulen** erfordern. Die erste Methode (FMZK + BEV-Kataster) bleibt als austauschbare Implementierung von Modul 2 erhalten und gilt weiterhin als **vorläufig**.

## Übersicht

```text
Modul 1: Datenbeschaffung, Zuschnitt und Validierung
   ├─ FMZK (GeoPackage, EPSG:31256)
   └─ Kataster (gst/nfl, BEV-Z16-Vektorkacheln; optionale Details)
                  │
                  ▼
Modul 2: Straßenraum ermitteln – Implementierung austauschbar
   Aktuell: FMZK-Kern + Kataster-nfl (95/65), vollständige FMZK-Polygone
                  │
                  ▼
      STANDARD-SCHNITTSTELLE: Straßenraum-GeoJSON (Polygone, EPSG:4326)
                  │
      ┌───────────┼──────────────────────┐
      ▼           ▼                      ▼
Modul 3        Modul 4              weitere Module
Bodenbegrünung Überschirmung        z.B. Versiegelung, Aufenthaltsqualität
      │           │                      │
      └───────────┼──────────────────────┘
                  ▼
       Spätere Kombination und Auswertung pro Straßenabschnitt
```

Die Module 3, 4 usw. beziehen ihre **Bezugsgeometrie** aus der gemeinsamen Straßenraum-Schnittstelle. Sie dürfen **nicht** voraussetzen, dass die Straßenraum-Objekte FMZK-Klassen, Kataster-KG/Grundstücksnummern oder spezifische Zuordnungsgründe enthalten.

## 1. Datenbeschaffung und Vorbereitung

**Aktuelle Bausteine:** `scripts/extract_fmzk.py`, `scripts/fmzk_source.py`, `scripts/analyze_kataster.py`.

- FMZK als lokale Originalquelle (`FMZK_WIEN_GP.gpkg`), Test-Extraktion nach `data/processed/fmzk_test.gpkg` (Layer `fmzk`, EPSG:31256) und Extraktionsmanifest `data/processed/fmzk_test.json`.
- BEV-Vektorkacheln `gst` (Grundstücke) und `nfl` (Nutzungsflächen), derzeit Zoomstufe 16; nur benötigter Ausschnitt mit Cache, getrennt von FMZK.
- Zusätzliche Grundstücks-API `/api/gst/<kgez>/<gnr>/` ist **optional**, da zeitweise nicht verfügbar. Fehlende Daten dürfen nicht in „nur Verkehr“ umgedeutet werden.
- Der gemeinsame, **rein lesende FMZK-Adapter** `scripts/fmzk_source.py` prüft Metadaten, Geometrien, CRS, Zuschnitt und Feature-Anzahl. Er gehört zu keinem fachlichen Straßenraum-Algorithmus.

**Grenze:** Datenbeschaffung und Dateiformate sind noch auf den kleinen lokalen Testausschnitt ausgelegt. Wienweite Verarbeitung kommt später.

## 2. Straßenraumgeometrie – austauschbare Erzeugung

**Aktuelle Implementierung:** `scripts/analyze_street_space.py`, `scripts/analyze_kataster.py`, `scripts/export_fmzk_strassenraum.py`.

Sie verbindet die FMZK-Kernklassen **21/23/24/33/39** mit der räumlichen Lage anderer FMZK-Polygone innerhalb der BEV-`nfl`-Nutzungen **95/65**. Die aktuell verwendete Schwelle beträgt 95 % Straßenmasken-Deckung und höchstens 5 % Überdeckung mit anderen Nutzungen. **Die Grenzen und offenen Fehlerfälle sind getrennt dokumentiert**: [Methodik FMZK/Kataster](Methodik-Strassenraum-FMZK-Kataster.md).

### Stabiler Übergabevertrag von Modul 2 zu den Kennzahlenmodulen (v1)

| Eigenschaft | Anforderung |
| --- | --- |
| Format | GeoJSON `FeatureCollection`, mit mindestens einem Polygon-`Feature` |
| Geometrietyp | `Polygon` oder `MultiPolygon`; alle Flächen werden für Berechnungen geometrisch vereinigt |
| Koordinaten | **EPSG:4326**, Koordinatenfolge `[Längengrad, Breitengrad]` gemäß GeoJSON |
| Ausdehnung | Derselbe Testausschnitt wie das dazugehörige FMZK-GeoPackage; kein stilles Abschneiden einer anderen Region |
| Attribute | **Nicht erforderlich**. `properties` können beliebig oder leer sein |
| Bedeutung | Vorläufig als Straßenraum betrachtete Boden-Bezugsfläche; keine rechtliche Feststellung |
| Versionierung | Dateipfad und **SHA-256 des Eingabe-GeoJSON** werden im Kennzahlenbericht erfasst; spätere Masken können verglichen werden |

**Derzeitige Maske:** `data/processed/street_space/fmzk_strassenraum.geojson`. Sie enthält noch FMZK-Originalobjekte und viele Attribute; **die nachfolgenden Module dürfen diese nicht benötigen**.

Ein späteres Verfahren – zum Beispiel eine verbesserte Kataster-Methode oder eine ganz andere Straßenraum-Erkennung – darf dieselbe Schnittstelle liefern. Dann müssen wir beim Kennzahlenmodul nur den Dateipfad ändern:

```bash
.venv/bin/python -m scripts.measure_ground_greening \
	--street-geojson data/processed/alternative/strassenraum.geojson
```

Wichtig: Eine solche neue Maske muss auch räumlich zum zugrunde liegenden FMZK-Testgebiet passen. Inkompatible Ausschnitte werden nicht heimlich verarbeitet.

## 3. Bodenbegrünungsanteil – jetzt implementiert

**Eigenständiges Kennzahlenmodul:** `scripts/measure_ground_greening.py`.

**Input 1:** ausschließlich **Straßenraum-Polygon-GeoJSON** laut Vertrag v1. Dabei werden Quellattribute absichtlich ignoriert.

**Input 2:** der **FMZK-Testausschnitt** via dem gemeinsamen `fmzk_source`-Adapter. Die bodengebundenen Grünflächen werden derzeit über `F_KLASSE IN (58,69)` identifiziert. `59` und andere Klassen werden nicht automatisch als Grün gezählt.

**Definition:**

```text
Nutzfläche Bodenbegrünung [m²] =
  Fläche( Vereinigen(FMZK-Grünpolygone 58/69) ∩ Straßenraumgeometrie )

Straßenraumfläche [m²] =
  Fläche( Vereinigen(alle Straßenraum-Polygone) )

Bodenbegrünungsanteil [%] =
  100 × Nutzfläche Bodenbegrünung / Straßenraumfläche
```

Alle Flächenberechnungen erfolgen **metrisch in EPSG:31256**. Dies verhindert das Doppeltzählen sich überdeckender FMZK-Geometrien und erlaubt neue Straßenraumquellen. Der Grün-Numerator wird **an der Straßenraumgrenze geschnitten**, unabhängig davon, ob Modul 2 ganze FMZK-Polygone ausgibt.

**Kennzahl ist bodengebunden:** Baumkronen über Asphalt oder Gehsteigen sind **keine** Bodenbegrünung, Gründächer sind nicht automatisch bodengebundene Straßenraumbegrünung. Außerdem ist diese Kennzahl nur so vollständig wie die FMZK-Grünklassifizierung und die vorläufige Straßenraumgrenze.

**Ausführung:**

```bash
.venv/bin/python -m scripts.measure_ground_greening
```

**Outputs (lokal; `data/processed/bodenbegruenung/`):**

- `bodenbegruenung_bericht.json`: Straßenraum-Gesamtfläche, vereinigte Boden-Grünfläche, Prozentanteil, Fläche nach Klasse 58/69, gegenseitige Überlagerungen, Zahl betroffener FMZK-Objekte, fehlende FMZK-Abdeckung, Eingabe-SHA-256 und Methodenhinweise.
- `bodenbegruenung_flaechen.geojson`: Zur Sichtprüfung nach Straßenraummaske **beschnittene Grün-Teilflächen** mit FMZK-FID und Klasse; die statistische Gesamtfläche wird **aus einer Vereinigungsgeometrie**, nicht aus der bloßen Addition dieser Features, berechnet.

**Kein Automatikschritt** zur Übernahme noch ungeklärter Grünflächen außerhalb der Straßenmaske. Sie bleiben für Qualitätskontrolle und spätere Verfeinerung erhalten. Die Gesamtrate bezieht sich ausschließlich auf die aktuelle vorläufige Maske.

## 4. Kronenüberschirmung – geplant, noch nicht implementiert

Eine spätere, unabhängige Datenquelle wird die projizierte Baumkronenfläche liefern; diese wird mit derselben Straßenraum-Maske geschnitten. Die Kennzahl **Kronenüberschirmungsgrad** ist unabhängig von der Bodenbegrünung und muss nicht mit ihr zu einer einzigen Flächenzahl addiert werden: Begrünter Boden und Baumkronen können übereinander liegen.

Wir legen heute **noch keine ungeprüfte Kronendatenquelle oder Klassenlogik** fest.

## 5. Weitere Kriterien – offen

Weitere getrennte Module können unter anderem zusätzliche räumliche und nutzungsbezogene Merkmale auswerten. Details und Datenquellen werden erst festgelegt, wenn sie benötigt werden. Auch die spätere Segmentierung, Aggregation und eine Gartenstraßen-Bewertung sind eigene Schritte, **nicht** Teil des jetzigen Bodenbegrünungsmoduls.

## Test-, Änderungs- und Vergleichsprinzipien

- **Modul 2 darf ausgetauscht werden**, ohne Modul 3 umzuschreiben: Der Test mit einem **attributfreien Polygon-GeoJSON** sichert das.
- Gleiche Eingabemaske + gleiche FMZK-Extraktion ergeben die gleichen geometrischen Kennzahlen; nur Zeitstempel unterscheiden sich.
- Flächen dürfen weder im Nenner (mehrere Straßenraumobjekte) noch im Zähler (überlappende Grünpolygone) mehrfach gezählt werden.
- Wenn die Straßenmaske Teile enthält, die durch **keine FMZK-Fläche** abgedeckt sind, wird dies ausgewiesen, nicht stillschweigend als vollständige Kartierung dargestellt.
- Ergebnisse sind **für den Testausschnitt**, nicht gleichzusetzen mit einer geprüften Genauigkeit für ganz Wien.
- Vor einem neuen oder revidierten Modul Datenvertrag, eindeutige Einheiten, Testfälle und eine neue fachliche Prüfung dokumentieren; nicht mehrere Schwellen gleichzeitig ohne Vergleichslauf ändern.

Die Daten und berechneten GeoJSONs bleiben lokal unter `data/`, nur Skripte, Tests und Dokumentation liegen auf GitHub.
