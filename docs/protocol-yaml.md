# Run a Protocol with YAML

YAML is the standard operator-facing protocol format and the path used by the
stock validation and run scripts.

## Before You Validate and Run

Check these before every run, not just the first one of the day:

- [ ] Candle, Universal Gcode Sender, or any other GRBL serial terminal is
      **closed** — only one program can hold the serial port.
- [ ] **Only the CUB you intend to run is connected** to this computer —
      connection is auto-scan with no way to target a specific device today,
      so a second connected CUB can get picked up instead.
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
   `packages/core/src/cubos/tools/validate_setup.py`.
3. **Run** the same three files with `packages/core/src/cubos/tools/run_protocol.py`.

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

Run `packages/core/src/cubos/tools/validate_setup.py` before connecting hardware, using the exact
gantry, deck, and protocol files intended for the run:

```bash
python -m cubos.tools.validate_setup \
  packages/core/configs/gantry/cub_xl_asmi.yaml \
  packages/core/configs/deck/asmi_deck.yaml \
  packages/core/configs/protocol/asmi/move_a1.yaml
```

Treat this as a required preflight after calibration changes, deck edits, gantry
edits, protocol edits, or before the first run of the day on a setup. Do not move
from offline review to physical motion until it passes. Offline validation
reduces risk, but it does not prove real-world clearance; confirm physical
fixture, cable, tool, and sample clearance before running.

## Run on hardware

After calibration, jog checks, and offline validation:

```bash
python -m cubos.tools.run_protocol \
  packages/core/configs/gantry/cub_xl_asmi.yaml \
  packages/core/configs/deck/asmi_deck.yaml \
  packages/core/configs/protocol/asmi/move_a1.yaml
```

`packages/core/src/cubos/tools/run_protocol.py` re-runs offline validation first, then connects to
the gantry and instruments, health-checks them, runs the protocol steps, and
disconnects when done. Measurement results are saved automatically.

By default, measurement rows are written to `data/databases/panda_data.db`.
Set `CUBOS_DATA_DB_PATH` to choose a different SQLite file for a run.
After a successful run, the CLI also writes analysis-friendly CSV exports under
`data/results/`. Array-based instruments such as UV-Vis, ASMI, and potentiostat
are flattened into one row per wavelength/sample point.

## Instruments

Instruments aren't declared in the protocol YAML — they're declared in the
**gantry YAML** during machine setup, under the top-level `instruments:` map.
The map key is the name protocol commands reference via `instrument: <name>`.
See [Set Up Gantry YAML: Define
Instruments](gantry-setup.md#define-instruments).

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
- `rinse_well`
- `flush_pipette`
- `purge_pipette`
- `clear_well`

### `home`

Home the gantry without rewriting the calibrated work-coordinate system —
whichever `origin_policy` the gantry YAML selects (see [Gantry: Origin
Policy](gantry.md#origin-policy)). No arguments.

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

Safety preflight runs before any motion: the request is rejected when the
volume is non-positive, below the configured pipette model's `min_volume`,
would draw a source vial below its `dead_volume_ul` floor, or would push the
destination above its `working_volume_ul` (dead-volume/overflow checks apply
when durable fluid tracking is active). Volumes above the model's
`max_volume` split automatically into capacity-bounded strokes; each stroke
is journaled durably, so a failure mid-transfer records exactly which strokes
applied and a rerun never re-applies committed liquid.

- `source` *(str, required)* — deck target to aspirate from.
- `destination` *(str, required)* — deck target to dispense into.
- `volume_ul` *(float, required)* — transfer volume (µL). May exceed the
  pipette model capacity (split into strokes).
- `speed` *(float, default `50.0`)* — aspirate/dispense speed.
- `source_height` *(float, default unset)* — engage offset at the source.
  When omitted and durable fluid tracking is active on a vial source with
  known `height`/`diameter`, the aspiration height is derived from the
  tracked liquid level (the tip follows the liquid down, floored at the
  dead-volume/bottom-clearance level). Pass an explicit value (including
  `0.0`) to bypass derivation; without tracking the legacy default `0.0`
  applies.
- `destination_height` *(float, default unset)* — engage offset at the
  destination; same explicit/derived rules as `source_height`.
- `liquid_class` *(str, default `null`)* — name of a volume-correction
  entry from the pipette instrument's `liquid_classes` gantry-YAML config
  (`{multiplier, offset_ul}` per class). The correction adjusts only the
  driver-commanded stroke volume; tracked fluid state always moves the
  requested volume. Disabled (identity) when omitted.

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

### Compound liquid commands

`rinse_well`, `flush_pipette`, `purge_pipette`, and `clear_well` express
reusable multi-step liquid-handling sequences by composing `transfer`/`mix`
(they add no new preflight or journaling of their own — every safety guard,
stroke split, and durable begin/complete step described under `transfer`
above applies to each transfer they issue). `mix`'s existing `repetitions`
argument already covers "mix N times"; there is no separate compound mix
command.

Each container argument is either an **explicit deck target** or
**automatic selection**:

- A stock source is exactly one of an explicit `source` (deck target) or a
  `solution` (canonical solution identity, e.g. `water`) that triggers
  automatic selection: the first `role: stock` container (see [Deck: Container
  Role And Solution Identity](deck.md#container-role-and-solution-identity))
  whose `solution` matches, visited in `sorted(deck labware key)` order (a
  matching `vial_grid` visits its positions in declared row-major order),
  with `tracked_volume - dead_volume_ul >= requested volume_ul`. The first
  eligible candidate in that order wins.
- A waste target is an explicit `waste` (deck target) or, when omitted,
  automatic selection: the first `role: waste` container in the same stable
  order whose `allowed_solutions` either is unset (accept-all) or contains
  the command's `solution`, with `tracked_volume + requested volume_ul <=
  working_volume_ul` (the same working-volume ceiling `transfer`'s
  destination-overflow guard uses, not raw `capacity_ul`).

Automatic selection requires durable fluid tracking (`context.fluid_state_id`)
— it needs a known current volume for every candidate. Explicit containers
work with or without tracking, identically to `transfer`. The resolved
automatic choice is logged (`<command> automatic <role> selection: solution=…
-> <position>`) and is durably recorded as the `transfer` operation's own
`source`/`destination` in the fluid-operation journal — no separate
selection-record table exists.

**Static validation scope.** When `validate_setup`/`run_protocol` is given
an `--initial-fluids` seed, automatic selection is resolved offline the same
way (see `cubos.validation.fluid_volumes`): the chosen container and the
resulting volumes are simulated exactly as at runtime, so dead-volume/waste-
headroom problems surface before any hardware run. Without an initial-fluids
seed, only a structural check runs: that at least one `role`/`solution`-
matching container is defined on the deck at all. In both cases, the
motion/collision bounds check (`_validate_pipette_engage` — working-volume
XYZ, machine-structure clearance, `safe_z`) only covers **explicit**
positions; the concrete container an automatic selection resolves to at
runtime is not fed back into that bounds pass. This is a deliberate,
documented gap: stock/waste vials are typically fixed deck fixtures whose
placement was already bounds-checked when added to the deck YAML, while the
volume-safety dimension (the primary risk for automatic selection) is fully
covered by fluid-volume simulation above.

#### `rinse_well`

Fill `well` from a stock source, optionally mix in place, then remove the
same volume to waste — `cycles` times.

- `well` *(str, required)* — deck target to rinse.
- `volume_ul` *(float, required)* — volume moved in and out each cycle.
- `cycles` *(int, default `3`)* — number of fill/remove cycles.
- `source` *(str, default unset)* / `solution` *(str, default unset)* —
  exactly one selects the stock source (see above).
- `waste` *(str, default unset)* — explicit waste target; omit for automatic
  selection.
- `mix_repetitions` *(int, default `0`)* — when `> 0`, mixes in `well` after
  each fill (see `mix`).
- `mix_volume_ul` *(float, default unset)* — mix volume; defaults to
  `volume_ul` when omitted.
- `speed` *(float, default `50.0`)*.
- `source_height` / `well_height` / `waste_height` *(float, default unset)* —
  engage offsets; same explicit/state-derived rules as `transfer`'s
  `source_height`/`destination_height`.

Durable substep keys (0-indexed cycles, extends `fluid_operation_key`):
`rinse:cycle{N}:fill`, `rinse:cycle{N}:mix` (only when `mix_repetitions >
0`), `rinse:cycle{N}:remove`.

#### `flush_pipette`

Draw from a stock source and dispense to waste, `cycles` times — one
`transfer` per cycle.

- `volume_ul` *(float, required)*.
- `cycles` *(int, default `1`)*.
- `source` / `solution` — exactly one, as above.
- `waste` *(str, default unset)* — explicit or automatic, as above.
- `speed` *(float, default `50.0`)*.
- `source_height` / `waste_height` *(float, default unset)*.

Substep keys: `flush:cycle{N}` (0-indexed).

#### `purge_pipette`

Empty the pipette's currently-loaded volume into waste — a single
`source -> waste` transfer. CubOS's durable fluid model has no volume
tracked independently "inside the tip" (`transfer` moves liquid atomically
source-to-destination in one journaled operation), so `source` must name
the container the currently-loaded liquid is attributed to, exactly like
`flush_pipette`'s per-cycle draw. It exists as distinct, intention-revealing
vocabulary for "empty what's in the tip right now" versus `flush_pipette`'s
"clean the tip with N cycles of fresh solvent."

- `volume_ul` *(float, required)*.
- `source` / `solution` — exactly one, as above.
- `waste` *(str, default unset)*.
- `speed` *(float, default `50.0`)*.
- `source_height` / `waste_height` *(float, default unset)*.

Substep key: `purge`.

#### `clear_well`

Remove `well`'s contents to waste until empty (or `target_volume_ul`).

- `well` *(str, required)*.
- `target_volume_ul` *(float, default `0.0`)* — volume left behind.
- `volume_ul` *(float, default unset)* — overrides the removed amount
  explicitly; otherwise the amount removed is `current_volume_ul -
  target_volume_ul` read from durable fluid state (requires tracking).
- `waste` *(str, default unset)* — explicit or automatic, as above.
- `solution` *(str, default unset)* — compatibility filter for automatic
  waste selection only (`clear_well` never selects its own source; `well` is
  always explicit).
- `speed` *(float, default `50.0`)*.
- `well_height` / `waste_height` *(float, default unset)*.

A no-op (no substep, no motion) when the computed removal volume is at or
below zero. Substep key: `clear`.

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
