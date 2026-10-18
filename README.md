# Gartenstraßen Wien

Analyse der Bodenbegrünung und Baumkronenüberschirmung des Wiener Straßenraums anhand von
SIS-Belagsflächen, dem GIP2-Straßennetz und dem Grünraummonitoring 2023.

## Einzige Verzeichnisstruktur

```text
ks-Gartenstrassen/
  code/                 # Python-Skripte, Tests, Methodik, Abhängigkeiten
    scripts/
    tests/
    docs/
    requirements-analysis.txt
  raw/                  # heruntergeladene WFS-/WMS-Originaldaten, dauerhaft
  work/                 # regenerierbare Arbeitsdaten, nach Erfolg löschbar
  output/               # aktuelle CSV, GeoJSON, PMTiles und Bericht
```

**Die beiden GeoPackages** unter `/mnt/c/Users/peter/Downloads/` werden **niemals beschrieben**.
Für den Wiener SIS-Lauf wird nur `gip_network_ogd.gpkg` im unveränderlichen
SQLite-Lesemodus verwendet. `FMZK_WIEN_GP.gpkg` bleibt unberührt.

## Ausführen

Die Python-Umgebung liegt wie bisher in `.venv/` am Repository-Root.

```bash
bash code/scripts/run-sis-v2-wien.sh
```

Die Quellen-Downloads verbleiben in `raw/`, temporäre Daten in `work/` und
die aktuellen Enddateien in `output/`. Dort liegen insbesondere
**`gip_abschnitte.geojson` und `gartenstrassen.pmtiles`** sowie CSV,
Bericht und `freigabe.json` als gemeinsamer Prüfsummennachweis.

Fertige Straßenraumkacheln und die separat gespeicherten Messkennzahlen
(`work/wien/messung.sqlite`) werden bei einem Abbruch anhand ihrer
Quellprüfsummen wiederverwendet. Erst nach erfolgreichem vollständigem
Lauf, gemeinsamer Veröffentlichung, QA-GPKG- und Ergebnisprüfung
wird ausschließlich `work/` entfernt. Bei Fehlern bleiben alle
Zwischenergebnisse zur Wiederaufnahme erhalten.

Für die spätere 20-m-Parallelkanten-Diagnose kann `work/` beibehalten werden:

```bash
SIS_WIEN_KEEP_WORK=1 bash code/scripts/run-sis-v2-wien.sh
bash code/scripts/run-gip-parallel-wien.sh
```

Parallelkanten werden bislang **nur erkannt, nicht vereinigt**. Die Veröffentlichung
enthält FOW 2/3/14 ab 100 m²; Fuß-/Radwege 15/504/505 dienen nur als
begleitende Infrastruktur beim Parallelabgleich.

**Dokumentation:** [Wien-Lauf](code/docs/Wien-Lauf.md),
[Methodik](code/docs/Methodik.md),
[FOW-Auswahl](code/docs/GIP-FOW-Auswahl.md),
[20-m-Parallelkanten](code/docs/Diagnose-Parallele-GIP-Achsen.md).

Die historischen V0-/Pilotskripte und Versuchsberichte sind nicht Teil des aktuellen
Projekts; die alte Historie ist weiterhin in Git nachvollziehbar.
