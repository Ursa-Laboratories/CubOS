# Data

CubOS stores experimental state and labware tracking data locally in a SQLite database. This runs automatically during protocol execution — no external database setup is needed.

## What Gets Stored

During a protocol run, the database records:

- **Campaigns** — top-level grouping for a set of experiments
- **Experiments** — individual runs within a campaign
- **Measurements** — per-well results from instruments (UV-Vis spectra, Filmetrics thickness, force data, etc.)
- **Labware state** — volume levels and contents for each well and vial, updated after every aspirate/dispense

## Reading Data Back

The `data.data_reader` module provides helper functions for extracting data from the SQLite database after a run. Use these to pull measurements, labware state, or campaign metadata into Python for your own analysis.

CubOS does not provide analysis tools — it only handles storage and retrieval. Analysis is left to the user.

## Runtime Integration

When `ProtocolContext.data_store` and `ProtocolContext.campaign_id` are set, protocol commands automatically persist measurements and liquid transfers. When these are not set, protocol execution works identically but nothing is saved.

## Components

- `data.data_store` — database creation and write API
- `data.data_reader` — read and query helpers
- `data.export_helpers` — CLI helpers for exporting stored data to CSV

## ASMI Raw CSV Export

Use `asmi-raw-csv` to export stored ASMI indentation measurements in the raw
per-well CSV format consumed by `projects/ASMI_new`:

```bash
PYTHONPATH=. python -m data.export_helpers \
  --db-path data/databases/panda_data.db \
  asmi-raw-csv <campaign_id> results/measurements/<run_folder>
```

Each ASMI measurement becomes a `well_<well>_<timestamp>.csv` file with
metadata rows followed by `Timestamp(s)`, `Z_Position(mm)`, `Raw_Force(N)`,
`Corrected_Force(N)`, and `Direction` when direction data is available.
