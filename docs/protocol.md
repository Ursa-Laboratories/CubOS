# Protocol

Protocols are ordered YAML step lists that compile into an executable `Protocol` object. At runtime, each step resolves to a registered command handler and executes against a shared `ProtocolContext`.

## Core Flow

1. Load protocol YAML.
2. Validate the schema and command arguments.
3. Compile each step into a `ProtocolStep`.
4. Inject a `ProtocolContext` containing the board, deck, logger, and optional persistence objects.
5. Run the steps sequentially.

## Config

Representative example:

```yaml
positions:
  park_position: [360.0, 260.0, 85.0]

protocol:
  # Home the gantry without redefining calibrated deck-origin WPos
  - home:

  # Scan all wells: travel at gantry safe_z to the first well, descend to
  # interwell_scan_height above each plate surface, then to measurement_height.
  - scan:
      plate: plate
      instrument: asmi
      method: indentation
      # Labware-relative offsets above the well surface (negative = below).
      measurement_height: -1.0       # 1 mm into the well surface
      interwell_scan_height: 8.0     # 8 mm above the well for between-wells travel
      indentation_limit_height: -5.0 # 5 mm into the well at deepest descent
      method_kwargs:
        step_size: 0.01
        force_limit: 10.0
        baseline_samples: 10
        measure_with_return: false  # true = down + return (up) sampling

  # Return to park position after scan
  - move:
      instrument: asmi
      position: park_position

  # Home the gantry
  - home:
```

Use this file when:

- changing the experimental sequence
- adding measurement or liquid-handling steps
- adjusting step parameters without changing the machine layout

## Available Commands

| Command | Description |
|---------|-------------|
| `move` | Move an instrument to a deck position |
| `scan` | Iterate all wells on a plate, calling an instrument method per well |
| `measure` | Move to one deck position, then call an instrument method |
| `pick_up_tip` | Pipette: pick up a tip |
| `aspirate` | Pipette: draw liquid |
| `transfer` | Pipette: combined move + aspirate + move + dispense |
| `serial_transfer` | Pipette: sequential transfers across positions |
| `mix` | Pipette: aspirate/dispense repeatedly |
| `blowout` | Pipette: blow out remaining liquid |
| `drop_tip` | Pipette: drop the tip |
| `home` | Home the gantry |
| `pause` | Pause execution for N seconds |
| `breakpoint` | Debug pause with user prompt |

`dispense` exists as an internal helper used by `transfer`, but it is not currently registered as a YAML protocol command.

## Position Values

The `move` command accepts:

- a named position from the top-level `positions` mapping
- raw `[x, y, z]` coordinates
- a deck target string such as `plate_1.A1` or `vial_1`

The `measure` command requires `instrument`, `position`, and
`measurement_height`. It travels XY at the gantry's absolute `safe_z`,
descends to `well.z + measurement_height` (where `well.z` is the
calibrated deck-frame surface Z of the resolved position), and calls
the selected method. The default method is `measure`.

## Heights on engaging commands

Heights are *labware-relative* offsets above the calibrated well/labware
surface Z (positive = above; negative = below) and are first-class
command arguments:

- `measurement_height` — required on `measure` and `scan`. Action plane
  offset.
- `interwell_scan_height` — required on `scan`. Between-wells XY-travel
  offset; must be at or above `measurement_height` in +Z-up.
- `indentation_limit_height` (ASMI scan) — signed labware-relative offset
  (mm above the well surface; negative = below). The deepest absolute Z
  reached during descent is `well.z + indentation_limit_height`. Must be
  at or below `measurement_height`. Legacy `indentation_limit` (sign-agnostic
  magnitude) and `z_limit` are rejected.

Pipette commands (aspirate/dispense/etc.) engage at the labware reference
Z (well bottom, tip top) — i.e. `measurement_height = 0` implicitly.
Inter-labware travel and the first-well entry of a scan use the gantry's
absolute `safe_z`, not these labware-relative fields.

Example:

```yaml
protocol:
  - measure:
      instrument: uvvis
      position: plate_1.A1
      method: measure
      measurement_height: 3.0
```

## Where Commands Live

The command implementations live under `src/protocol_engine/commands/`.

## Authoring Guidance

- Prefer explicit instrument names instead of relying on implicit defaults
- Use deck targets like `plate.A1` rather than hardcoded coordinates when possible
- Keep hardware-setup changes in deck or board config, not in protocol YAML
- Treat protocols as experiment definitions, not as calibration files
