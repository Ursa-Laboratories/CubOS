# Data

CubOS stores experimental state and labware tracking data locally in a SQLite database. This runs automatically during protocol execution when a `DataStore` is attached — no external database setup is needed.

By default `data.DataStore()` writes to CubOS' package-owned
`data/databases/panda_data.db`. Set `CUBOS_DATA_DB_PATH` to place the database
in a writable runtime directory, such as a packaged app's local user-data root.

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

When `ProtocolContext.data_store` and `ProtocolContext.campaign_id` are set, protocol commands automatically persist measurements and liquid transfers. `scan` persists per-well measurements, and single-position `measure` persists normalized ASMI indentation results. When these are not set, protocol execution works identically but nothing is saved.

## Components

- `data.data_store` — database creation and write API
- `data.data_reader` — read and query helpers
- `data.data_store.default_database_path` — default database path and `CUBOS_DATA_DB_PATH` override
