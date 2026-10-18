# Wiener Gesamtlauf

Vom Repository-Root aus ausführen:

```bash
git status --short
git pull --ff-only
bash code/scripts/run-sis-v2-wien.sh
```

**Quelle unter Windows (nur lesen):**
`/mnt/c/Users/peter/Downloads/gip_network_ogd.gpkg`. Die Datei
`FMZK_WIEN_GP.gpkg` im selben Ordner wird für die aktuelle SIS-Pipeline
nicht benötigt. Keine Kopien, Sicherungsdateien, Datenbanken oder SQLite-Sidecars
in Downloads erzeugen.

**Daten im Repository:**

- `raw/aoi/`: amtliche Bezirksgrenzen und Wien-AOI
- `raw/sis/wfs-kacheln/`: heruntergeladene, komprimierte Originalantworten
- `raw/grm2023/png/`: GRM-PNGs und Herkunftsmetadaten
- `work/`: SIS-/GIP-Indizes, Straßenräume, Partitionen, Kronenmasken
- `output/`: `gip_abschnitte.csv`, `gip_abschnitte.geojson`,
  `bericht.json`, `gartenstrassen.pmtiles`

Die heruntergeladenen Dateien werden bei einem unterbrochenen Lauf aus
`raw/` wiederverwendet. **Nur nach einem erfolgreichen vollständigen Lauf**
und automatischer Validierung werden die regenerierbaren `work/`-Daten
entfernt. Bei einem Fehler bleiben diese erhalten.

Vor einer 20-m-Diagnose den Index aufbewahren:

```bash
SIS_WIEN_KEEP_WORK=1 bash code/scripts/run-sis-v2-wien.sh
bash code/scripts/run-gip-parallel-wien.sh
```

Nur das PMTiles aus dem vorhandenen GeoJSON neu erzeugen:

```bash
bash code/scripts/run-sis-v2-wien.sh --from pmtiles --until pmtiles
```

Nur `work/` nach Prüfung entfernen:

```bash
PYTHONPATH=code .venv/bin/python -m scripts.clean_wien_work
PYTHONPATH=code .venv/bin/python -m scripts.clean_wien_work --apply
```

Das zweite Kommando löscht ausschließlich `work/`, niemals `raw/`,
`output/` oder die Windows-GeoPackages.

**Hinweis für lokale Git-Änderungen:** Die Optimierungen der neun lokal
gestagten Dateien wurden bereits mit PR #7 nach `main` übernommen.
Vor der Aktualisierung der Arbeitskopie diese ggf. mit
`git stash push -m "SIS-Optimierungen bereits auf main"` sichern.
Kein `git reset --hard`.
