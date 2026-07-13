# Zoo Repo Overview

## Purpose

`Zoo` is a local web UI for `CubOS`. It edits YAML configs, visualizes deck state, controls gantry motion, and triggers protocol execution through CubOS APIs and classes.
Protocol editing exposes top-level `positions` mappings in a separate Named
Positions panel and saves them with the step list. The protocol Validate button
calls CubOS offline setup validation for the selected gantry, deck, and
protocol files rather than only checking command schemas.
Malformed config YAML is surfaced as a load error, and hardware controls stay
disabled until the selected gantry file loads through CubOS validation. Deck
and gantry save paths validate the converted CubOS YAML before overwriting the
target file.
Protocol runs are blocked while CubOS reports an active gantry calibration warning;
operators can still connect and calibrate so new controllers can be brought into
the expected GRBL state.

The gantry control surface also exposes a calibration wizard that turns CubOS'
`setup/calibrate_gantry.py` flow into a guided UI. Operators still use CubOS
movement semantics through Zoo jog/home/connect endpoints; the persistent
connection, serial operation lock, cached status, manual movement guards, and
calibration soft-limit state are owned by CubOS `GantrySession`. The wizard
saves the calibrated YAML through the same schema-validated gantry config path.
The gantry control surface includes an Advanced mode for live-controller
recovery and inspection through CubOS session methods: read GRBL settings,
send one numeric GRBL setting, clear alarms, reset + unlock, feed hold, and
jog cancel.
The wizard is intentionally serial: after the operator selects the reference
and lowest instrument, Zoo runs the blocking controller-prep/home steps, locks
controls during automatic home/center/retract moves, and only exposes the next
operator action when the current step completes.

The protocol editor derives operator choices from the loaded deck, gantry, and
protocol file: plate fields use available well plates, instrument fields use
mounted instruments, position fields use deck targets plus top-level protocol
positions, and measurement method fields use instrument-aware options. ASMI
indentation method options expose force limit, step size, baseline samples, and
measure-with-return controls.
The gantry editor gets supported instrument types, vendors, and vendor-specific
constructor fields from CubOS registry endpoints; it does not maintain a local
driver registry. Fresh Windows installs start from generic `cub_seed.yaml` and
`cub_xl_seed.yaml` gantry templates and generic `cub_deck_example.yaml` and
`cubxl_deck_example.yaml` deck templates, then rely on this editor for
operators to choose and save the mounted instruments for their machine.
Protocol execution is gated on the gantry position poll reporting an active
connection. Each Run Protocol request delegates to `GantrySession.run_protocol()`,
which creates one CubOS `DataStore` campaign for the selected gantry, deck, and
protocol files, registers nested deck labware, executes the saved protocol
against the already-connected gantry, and returns `campaign_id`. While the request is pending, the
frontend keeps the running state visible and offers a Cancel Run control that
requests CubOS gantry feed hold.
The Results view reads the CubOS `DataStore` SQLite path by default, or
`ZOO_DATA_DB_PATH` when explicitly set, through CubOS data export helpers. It lets operators export campaign
measurement rows as ZIPs of raw CSV files for each CubOS instrument measurement
table that has rows in the selected campaign. The ASMI-only per-well ZIP remains available for the
`projects/ASMI_new` analysis workflow.

The standard CubOS HTTP surface is rooted at `/api/v1`. Discovery endpoints are
hardware-safe. Protocol submissions are asynchronous addressable resources:
the server writes immutable input bundles, SHA-256 digests, lifecycle events,
results, and failures beneath the configured run directory. The run manager
reuses Zoo's persistent CubOS `GantrySession` and run gate, so the API does not
create a competing hardware owner. Optional command/instrument allow-lists,
gantry/deck digest pins, and a bearer token are configured through `ZOO_*`
settings for appliance deployments.

## Key Directories

| Path | Purpose |
| --- | --- |
| `zoo/app.py` | FastAPI app factory |
| `zoo/__main__.py` | Startup entrypoint |
| `zoo/config.py` | `ZOO_*` settings and config-directory handling |
| `zoo/routers/` | REST endpoints, including the versioned CubOS discovery and run API |
| `zoo/services/` | YAML helpers plus durable asynchronous run management |
| `../web/src/` | React + TypeScript application |
| `../web/src/components/gantry/` | Gantry jog/readout controls and calibration wizard |
| `configs/` | Generic gantry and deck seed templates for fresh installs |
| `tests/` | Backend tests |

## Main Entrypoints

- `python -m zoo`
- `uvicorn zoo.app:create_app --factory`
- `cd ../web && npm run dev`

## How To Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cd ../web
npm ci
cd ..
python -m zoo
```

## How To Test

Backend:

```bash
pytest tests/
```

Frontend:

```bash
cd ../web
npm run lint
npm run test
npm run build
```

## Lint And Format

- Frontend lint command exists: `npm run lint`
- No backend formatter or linter configuration was confirmed in the first pass

## Deployment Or Release Role

- Local operator-facing UI
- Depends on the published or installable `CubOS` package
- `installer/windows/` builds a Windows operator installer from Zoo `main` and
  CubOS `main`; the generated installer includes a private Python runtime,
  retains the bundled Python installer for launcher repair, prebuilt frontend
  assets, an offline wheelhouse, Start Menu shortcuts, config seeding, logs,
  and diagnostic export.

## Dependencies On Other Repos Or Services

- Depends on `CubOS` from Git in `pyproject.toml`
- Requires Node.js for frontend development and build
- Deck editing and visualization use CubOS' current deck YAML field names (`length`, `width`, `height`, `x_offset`, `y_offset`, `diameter`).
- Talks directly to local gantry hardware through CubOS `GantrySession` when operators use motion endpoints
- Manual absolute `Move To` commands are validated by CubOS against the connected gantry's loaded `working_volume` before motion starts.
- Data export uses CubOS helpers over the same SQLite schema CubOS writes for campaigns,
  experiments, and instrument measurement tables; Zoo does not analyze the data.
- Gantry calibration delegates work-coordinate, soft-limit, and limit-recovery operations to CubOS `GantrySession`; Zoo only sequences the operator UI and YAML save. During XY origining, CubOS may temporarily disable stale soft limits and restores them on cancel, single-instrument XY completion, disconnect, or successful soft-limit programming. Zoo preserves `cnc.factory_z_travel_mm` as the out-of-box safety bound, reads `cnc.calibration_block_height_mm`, and writes calibrated Z bounds from home-to-block travel plus the final homed readback. `working_volume` is the usable deck/WPos range; saved GRBL `max_travel_*` values are controller soft-limit spans that include the `$27` homing pull-off reserve. Calibration sets `$10=0` for WPos reports and writes the machine's configured `homing_pull_off` before homing so MPos/WCO reporting does not leak into deck-origin math. If an interactive calibration jog or automatic blocking retract trips a GRBL alarm, Zoo stops repeated jogs, locks calibration controls, tells the operator a limit was hit, and calls CubOS limit recovery before allowing calibration to continue. Disconnect surfaces soft-limit restore failures instead of silently reporting success.
- Advanced gantry recovery endpoints still route through CubOS session methods; Zoo does not expose arbitrary raw serial command entry.

## Known Pitfalls

- Fresh installed config directories are seeded only with generic gantry and
  deck templates; first-time users still need to pick instruments in the Gantry
  editor, then add or redirect protocol configs as needed.
- `python -m zoo` may build the frontend automatically if `frontend/dist/` is absent.
- The shared CubOS `GantrySession` is process-local and serial access is deliberately locked inside CubOS.
- `raw` endpoints bypass schema-aware editing and can write malformed YAML if used carelessly.
- The checked-in frontend README is a template and not authoritative project documentation.
- Current CubOS configs no longer use a separate mounted-instrument config in Zoo; instruments belong in gantry YAML.
- Calibration can write a new gantry YAML and optionally program live GRBL soft-limit settings, so it should not be exercised without hardware clearance and an E-stop within reach.
