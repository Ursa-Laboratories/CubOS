# Run a Protocol with YAML

YAML is the standard operator-facing protocol format and the path used by the
stock validation and run scripts.

## Before You Validate and Run

Check these before every run, not just the first one of the day:

- [ ] Candle, Universal Gcode Sender, or any other GRBL serial terminal is
      **closed** — only one program can hold the serial port.
- [ ] **Only the CUB you intend to run is connected** to this computer —
      connection is auto-scan with no way to target a specific device today,
      so a second connected CUB can get picked up instead (see
      [Calibration: Multi-CUB Serial Ports](calibration.md#multi-cub-serial-ports)).
- [ ] The gantry is **homed** (or you're about to home as the first protocol
      step) — don't run motion on an unhomed or previously-alarmed gantry.
- [ ] The **deck YAML matches the physical deck** — labware placement,
      holder nesting, and calibration anchors reflect what's actually on the
      bench right now.
- [ ] Mounted **instruments are powered on** and, where applicable,
      connected/initialized before the run starts.

## High-level workflow

The YAML path has three user-facing steps:

1. **Write** a protocol YAML file.
2. **Validate** the gantry, deck, and protocol together with
   `setup/validate_setup.py`.
3. **Run** the same three files with `setup/run_protocol.py`.

The sections below cover that workflow first. Detailed command arguments come
later in [Protocol command reference](#protocol-command-reference).

## Write a protocol file

A protocol YAML file is an optional `positions:` map of named coordinates plus an
ordered `protocol:` list of commands:

```yaml
positions:
  park: [280.0, 280.0, 85.0]

protocol:
  - home: {}
  - move:
      instrument: asmi
      position: plate.A1
  - home: {}
```

Each list entry is a single command keyed by its name (see
[Protocol command reference](#protocol-command-reference) below). The schema is
strict — an unknown key under a command is rejected.

## Validate offline

Run `setup/validate_setup.py` before connecting hardware, using the exact
gantry, deck, and protocol files intended for the run:

```bash
python setup/validate_setup.py \
  configs/gantry/cub_xl_asmi.yaml \
  configs/deck/asmi_deck.yaml \
  configs/protocol/asmi/move_a1.yaml
```

Treat this as a required preflight after calibration changes, deck edits, gantry
edits, protocol edits, or before the first run of the day on a setup. Do not move
from offline review to physical motion until it passes. Offline validation
reduces risk, but it does not prove real-world clearance; confirm physical
fixture, cable, tool, and sample clearance before running.

## Run on hardware

After calibration, jog checks, and offline validation:

```bash
python setup/run_protocol.py \
  configs/gantry/cub_xl_asmi.yaml \
  configs/deck/asmi_deck.yaml \
  configs/protocol/asmi/move_a1.yaml
```

`setup/run_protocol.py` performs two phases:

1. Offline setup validation.
2. The hardware run: construct the gantry from YAML, re-load and re-validate the
   configs, connect the gantry, clear any startup alarm, connect instruments,
   run the health check, execute the steps, and disconnect the instruments and
   gantry in cleanup. Persistable measurement results are saved to a SQLite
   data campaign automatically.

By default, measurement rows are written to `data/databases/panda_data.db`.
Set `CUBOS_DATA_DB_PATH` to choose a different SQLite file for a run.
After a successful run, the CLI also writes analysis-friendly CSV exports under
`data/results/`. Array-based instruments such as UV-Vis, ASMI, and potentiostat
are flattened into one row per wavelength/sample point.

## Defining Instrument Drivers

Instruments aren't declared in the protocol YAML — they're declared in the
**gantry YAML**, under the top-level `instruments:` map (see
[Gantry: Config](gantry.md#config)). The map key is the name protocol
commands reference via `instrument: <name>`.

Every instrument entry needs at minimum:

- `type` *(str, required)* — a type from `src/instruments/registry.yaml`
  (`asmi`, `filmetrics`, `pipette`, `potentiostat`, `uv_curing`, `uvvis_ccs`,
  `camera`, `mounted_tool`).
- `vendor` *(str, required)* — a vendor registered for that type. The
  `type`/`vendor` pair is how CubOS resolves which Python driver class to
  load — you don't give a driver path directly unless you're registering an
  external driver package (via the `cubos.instrument_registries` entry point
  group or a `CUBOS_INSTRUMENT_REGISTRY_PATHS` overlay — see
  [Getting Started](getting-started.md#instrument-extras)).
- `offset_x`, `offset_y`, `depth` *(float, default `0.0`)* — physical
  mounting offsets from the gantry's reference point.

Everything else is driver-specific and passes straight through to the
vendor driver's constructor (`extra="allow"` in the schema) — this is where
a **device serial number**, COM/serial **port**, or a **driver file path**
(e.g. a vendor DLL) shows up, when the driver needs one. Set `offline: true`
to run a driver in its synthetic/no-hardware mode.

One worked example per instrument type:

**`asmi` / `vernier`** — Vernier Go Direct force sensor. No serial number
needed; the `godirect` SDK auto-detects the sensor over USB.

```yaml
instruments:
  asmi:
    type: asmi
    vendor: vernier
    offset_x: 0.0
    offset_y: 0.0
    depth: 0.0
    force_threshold: -50
    sensor_channels: [1]
```

**`filmetrics` / `kla`** — KLA Filmetrics thin-film measurement, driven
through a vendor executable and recipe file:

```yaml
instruments:
  filmetrics:
    type: filmetrics
    vendor: kla
    offline: true
    offset_x: 0.0
    offset_y: 0.0
    depth: 0.0
    exe_path: "C:\\Filmetrics\\Filmeasure.exe"
    recipe_name: "my_recipe"
```

**`pipette` / `opentrons`** — Opentrons pipette over a serial connection:

```yaml
instruments:
  pipette:
    type: pipette
    vendor: opentrons
    pipette_model: p300_single_gen2
    port: "COM7"
    baud_rate: 115200
    offline: true
    offset_x: 180.0
    offset_y: -25.0
    depth: 0.0
```

**`potentiostat` / `admiral`** — Admiral SquidStat, addressed by serial port
and channel number:

```yaml
instruments:
  potentiostat:
    type: potentiostat
    vendor: admiral
    port: "/dev/ttyACM1"
    channel: 0
    offline: true
    offset_x: -55.0
    offset_y: 0.0
    depth: 58.0
```

**`uv_curing` / `excelitas`** — Excelitas UV curing lamp over serial:

```yaml
instruments:
  uv_curing:
    type: uv_curing
    vendor: excelitas
    offline: true
    offset_x: 0.0
    offset_y: 0.0
    depth: 0.0
    port: "/dev/ttyACM0"
    baud_rate: 19200
    default_intensity: 100.0
    default_exposure_time: 1.0
```

**`uvvis_ccs` / `thorlabs`** — Thorlabs CCS spectrometer, addressed by
**device serial number** plus the vendor **driver DLL path**:

```yaml
instruments:
  uvvis_ccs:
    type: uvvis_ccs
    vendor: thorlabs
    offline: true
    offset_x: 0.0
    offset_y: 0.0
    depth: 0.0
    serial_number: "M00123456"
    dll_path: "TLCCS_64.dll"
    default_integration_time_s: 0.24
```

**`camera` / `mount_only`** (or `raspberry_pi`) — a fixed-mount camera with
no active driver, used as a positional reference:

```yaml
instruments:
  camera:
    type: camera
    vendor: mount_only
    offline: true
    offset_x: 0.0
    offset_y: 0.0
    depth: 32.0
```

**`mounted_tool` / `mount_only`** — any other passive mounted tool (e.g. a
vial capper/decapper) tracked for offsets only:

```yaml
instruments:
  vial_capper_decapper:
    type: mounted_tool
    vendor: mount_only
    offline: true
    offset_x: 58.0
    offset_y: 0.0
    depth: 48.0
```

## Protocol command reference

Each command is one entry in the `protocol:` list. Arguments map directly to the
command's handler: parameters without a default are **required**, the rest are
optional and fall back to the default shown (defaults are applied at run time and
are not written into the stored step). The schema is strict — unknown keys are
rejected.

Two conventions apply throughout:

- **Deck targets** are labware paths — top-level like `plate.A1` or nested like
  `plate_holder.plate.A1`.
- **Height arguments** (`measurement_height`, `interwell_scan_height`, pipette
  `height`, …) are labware-relative offsets in mm: positive is above the
  labware surface Z, negative is below.

Commands available in YAML:

- `home`
- `move`
- `measure`
- `scan`
- `pause`
- `breakpoint`
- `pick_up_tip`
- `aspirate`
- `blowout`
- `mix`
- `transfer`
- `serial_transfer`
- `drop_tip`

### `home`

Home the gantry without rewriting the calibrated deck-origin work-coordinate
system. No arguments.

### `move`

Move an instrument to a position. A named position or literal `[x, y, z]` gets a
raw gantry move; a deck-target string routes through the safe `move_to_labware`
approach and ends **above** the target (no descent).

- `instrument` *(str, required)* — instrument registered on the gantry.
- `position` *(required)* — a named position (from `positions:`), an `[x, y, z]`
  list, or a deck-target string.
- `travel_z` *(float, default `null`)* — transit Z for literal/named XYZ moves:
  lift/lower to `travel_z` at the current XY, travel XY, then move to `position`.
  Applies **only** to literal/named targets; supplying it with a deck target is
  an error.

### `measure`

Travel to a deck position, descend to `well.z + measurement_height`, call an
instrument method, and persist the result if a campaign is attached.

- `instrument` *(str, required)* — instrument registered on the gantry.
- `position` *(str, required)* — deck target to measure at.
- `measurement_height` *(float, required)* — labware-relative offset for the
  action plane.
- `method` *(str, default `"measure"`)* — instrument method to call.
- `indentation_limit_height` *(float, default `null`)* — signed labware-relative
  offset for the deepest descent plane (closed-loop methods such as ASMI
  `indentation`); must be at or below `measurement_height`.
- `method_kwargs` *(dict, default `{}`)* — forwarded verbatim to the instrument
  method. See [method_kwargs](#method_kwargs) below.

### `scan`

Scan every well of a plate in row-major order (A1, A2, …, B1, …), calling an
instrument method at each well. Returns a `{well_id: result}` mapping.

- `plate` *(str, required)* — deck key resolving to a `WellPlate`.
- `instrument` *(str, required)* — instrument registered on the gantry.
- `method` *(str, required)* — method to call per well.
- `measurement_height` *(float, required)* — labware-relative action plane.
- `interwell_scan_height` *(float, required)* — labware-relative offset for
  between-well XY travel; must be at or above `measurement_height`.
- `indentation_limit_height` *(float, default `null`)* — deepest plane for ASMI
  indentation; must be at or below `measurement_height`.
- `delay_s` *(float, default `0.0`)* — seconds to pause between wells.
- `method_kwargs` *(dict, default `null`)* — forwarded to the method per well.

### `pause`

Pause execution for a fixed duration.

- `seconds` *(float, required)* — duration to pause.
- `reason` *(str, default `""`)* — logged with the pause message.

### `breakpoint`

Halt until the operator presses Enter.

- `message` *(str, default `"Press Enter to continue..."`)* — prompt shown.

### Pipette commands

All pipette commands require an instrument registered under the name `pipette`.
The `height`/`source_height`/`destination_height` args follow the labware-relative
height convention.

#### `pick_up_tip`

Pick up a tip from a tip-rack slot, record its length, and mark the slot consumed.

- `position` *(str, required)* — tip-rack slot, including the explicit tip slot
  (e.g. `tips.A1`).
- `speed` *(float, default `50.0`)* — approach/pick-up speed.

#### `aspirate`

Move to a position and aspirate.

- `position` *(str, required)* — deck target to aspirate from.
- `volume_ul` *(float, required)* — volume to aspirate (µL).
- `speed` *(float, default `50.0`)* — aspirate speed.
- `height` *(float, default `0.0`)* — engage offset.

#### `blowout`

Move to a position and blow out.

- `position` *(str, required)* — deck target.
- `speed` *(float, default `50.0`)* — blowout speed.
- `height` *(float, default `0.0`)* — engage offset.

#### `mix`

Move to a position and mix in place (repeated aspirate/dispense).

- `position` *(str, required)* — deck target.
- `volume_ul` *(float, required)* — mix volume (µL).
- `repetitions` *(int, default `3`)* — number of mix cycles.
- `speed` *(float, default `50.0`)* — mix speed.
- `height` *(float, default `0.0`)* — engage offset.

#### `transfer`

Aspirate from a source and dispense into a destination (records the dispense with
its source labware).

- `source` *(str, required)* — deck target to aspirate from.
- `destination` *(str, required)* — deck target to dispense into.
- `volume_ul` *(float, required)* — transfer volume (µL).
- `speed` *(float, default `50.0`)* — aspirate/dispense speed.
- `source_height` *(float, default `0.0`)* — engage offset at the source.
- `destination_height` *(float, default `0.0`)* — engage offset at the
  destination.

#### `serial_transfer`

Transfer from one source to each well along a plate row or column, with per-well
volumes given explicitly or interpolated.

- `source` *(str, required)* — deck target to aspirate from.
- `plate` *(str, required)* — deck key resolving to a `WellPlate`.
- `axis` *(str, required)* — a row letter (e.g. `"A"`) or column number (e.g.
  `"3"`) selecting the wells.
- `volumes` *(list of float, default `null`)* — explicit per-well volumes; length
  must equal the well count on the axis.
- `volume_range` *(`[min, max]`, default `null`)* — linearly spaced across the
  axis.
- `speed` *(float, default `50.0`)* — aspirate/dispense speed.
- `source_height` *(float, default `0.0`)* — engage offset at the source.
- `destination_height` *(float, default `0.0`)* — engage offset at each
  destination.

`volumes` and `volume_range` are **mutually exclusive** — provide exactly one.

#### `drop_tip`

Move to a position and drop the tip.

- `position` *(str, required)* — deck target where the tip is dropped.
- `speed` *(float, default `50.0`)* — approach/drop speed.

### method_kwargs

`measure` and `scan` forward `method_kwargs` verbatim to
`instrument.<method>(...)`. Its keys are **instrument-method-specific and are not
validated by the command schema** — they depend entirely on the method you name
(for example an ASMI `indentation` method may accept `step_size`, `force_limit`,
`baseline_samples`). The one restriction: a fixed set of reserved height keys is
rejected inside `method_kwargs` — `measurement_height`, `interwell_scan_height`,
`indentation_limit_height`, `entry_travel_height`, `interwell_travel_height`,
`safe_approach_height`, `z_limit`, `indentation_limit` — because the engine owns
those. The engine also injects `well_z`, `measurement_height`,
`indentation_limit_height`, and `gantry` into the method call when (and only when)
the method declares those parameters; injected values win over `method_kwargs`.
