# Data

CubOS stores campaign state, experiment rows, measurement results, and labware
contents in a local SQLite database. Standard hardware runs attach a `DataStore`
automatically. No external database server is required.

## Database Path

`DataStore()` uses:

```text
data/databases/panda_data.db
```

Override it with `CUBOS_DATA_DB_PATH` or pass a path explicitly:

```python
from data import DataStore

store = DataStore("runs/example.db")
```

`DataStore(":memory:")` creates an in-memory SQLite database for tests.

## What Gets Stored

`data.data_store.DataStore` creates these tables:

| Table | Contents |
| --- | --- |
| `campaigns` | Run grouping, config path metadata, creation time, status. |
| `experiments` | One row per measured labware location within a campaign. |
| `uvvis_measurements` | Wavelengths, intensities, integration time. |
| `filmetrics_measurements` | Thickness and goodness-of-fit. |
| `uv_curing_measurements` | UV intensity, exposure duration, and cure timestamp. |
| `camera_measurements` | Image path results. |
| `asmi_measurements` | Force/z/time series, baseline stats, force-limit metadata. |
| `potentiostat_measurements` | OCP/CA/CV/CP time, voltage, current, and technique metadata. |
| `labware` | Per-well or per-vial volume and contents tracking. |

Measurement arrays are stored as JSON text inside SQLite columns.

## Runtime Persistence

Protocol commands persist data when both runtime fields are present:

- `ProtocolContext.data_store`
- `ProtocolContext.campaign_id`

`setup/run_protocol.py`, `protocol_engine.setup.run_on_hardware()`, and
`Protocol.run()` create and attach those fields automatically when the caller
does not supply them.

`scan` creates one experiment row per well and logs each normalized
measurement. `measure` creates one experiment row for the target position and
logs the normalized result. Pipette `transfer` updates destination labware
contents through `record_dispense()`.

Normalized measurement persistence covers ASMI indentation, UV-Vis spectra,
Filmetrics thickness, potentiostat traces, and UV curing exposure results.
Boolean status checks and other non-data method results are not persisted.

Low-level `protocol.execute(context)` only saves data if the caller prepared a
context with a `DataStore` and `campaign_id`.

## Write API

Common write-side calls:

```python
from data import DataStore

with DataStore("runs/example.db") as store:
    campaign_id = store.create_campaign(
        "ASMI indentation",
        gantry_config="configs/gantry/cub_xl_asmi.yaml",
        deck_config="configs/deck/asmi_deck.yaml",
        protocol_config="configs/protocol/asmi/indentation.yaml",
    )
    # Protocol commands normally create experiments and measurements.
```

`DataStore.log_measurement()` accepts normalized
`protocol_engine.measurements.InstrumentMeasurement` objects, UV-Vis spectra,
Filmetrics results, UV curing exposure results, and camera image paths. ASMI and
potentiostat results are normalized in `protocol_engine.measurements` before
they are written.

## Read API

`data.data_reader.DataReader` is a read-only query layer:

```python
from data.data_reader import DataReader

with DataReader(db_path="runs/example.db") as reader:
    campaigns = reader.list_campaigns()
    experiments = reader.get_experiments(campaign_id=1)
    labware = reader.get_labware(campaign_id=1)
    asmi_rows = reader.get_measurements_by_campaign(
        campaign_id=1,
        table="asmi_measurements",
    )
```

Generic measurement readers currently allow these tables:

- `uvvis_measurements`
- `filmetrics_measurements`
- `uv_curing_measurements`
- `camera_measurements`
- `asmi_measurements`
- `potentiostat_measurements`

## CSV Export

CSV and ZIP export is implemented in `data.export_helpers`,
`data.exports`, and the `DataReader.export_dataframe_to_csv()` method.
The DataFrame helpers require pandas:

```bash
pip install pandas
```

List experiment IDs for a campaign:

```bash
python -m data.export_helpers \
  --db-path runs/example.db \
  campaign-experiments 1 \
  --csv runs/campaign_1_experiments.csv
```

Export all measurements for one experiment:

```bash
python -m data.export_helpers \
  --db-path runs/example.db \
  experiment-all 42 \
  --csv runs/experiment_42_measurements.csv
```

Export one supported instrument table for an experiment:

```bash
python -m data.export_helpers \
  --db-path runs/example.db \
  experiment-instrument 42 asmi \
  --csv runs/experiment_42_asmi.csv
```

If `--csv` is omitted, the helper prints the DataFrame to stdout.

`data.exports` provides UI/API-safe helpers for campaign summaries,
multi-table measurement ZIPs, and the ASMI raw CSV ZIP:

```python
from data import (
    export_campaign_asmi_zip,
    export_campaign_measurements_zip,
    list_campaign_summaries,
)

summaries = list_campaign_summaries("runs/example.db")
zip_bytes = export_campaign_measurements_zip("runs/example.db", campaign_id=1)
asmi_zip_bytes = export_campaign_asmi_zip("runs/example.db", campaign_id=1)
```

Protocol-run campaign setup for wrappers lives in
`data.protocol_runs.create_campaign_for_protocol_run()`. It creates the
campaign, registers nested deck labware recursively, and returns the
`campaign_id` used by `ProtocolContext`.

## Modules

- `data.data_store` - SQLite schema and write API
- `data.data_reader` - read-only query and DataFrame helpers
- `data.exports` - campaign summaries and ZIP export helpers
- `data.protocol_runs` - protocol-run campaign and labware registration helpers
- `data.export_helpers` - CLI wrappers for CSV/table export
- `data.analysis.uvvis` - UV-Vis analysis helper module
