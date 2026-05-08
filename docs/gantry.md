# Gantry

The gantry is the CNC motion platform that moves instruments over the deck.
CubOS communicates with GRBL-based controllers over serial.

## Coordinate Convention

The high-level gantry boundary uses the CubOS deck frame:

- origin `(0, 0, 0)` is the front-left-bottom reachable work volume
- `+X` moves right from the operator perspective
- `+Y` moves away from the operator, toward the back of the deck
- `+Z` moves up, away from the deck
- `-Z` moves down, toward the deck

The low-level controller may physically home at the opposite back-right-top
corner. That machine-frame detail stays at the controller/GRBL boundary. CubOS
does not apply a hidden Z sign flip in the high-level `Gantry` wrapper.

Protocol `home` runs GRBL `$H` and preserves the calibrated G54 WPos frame. It
does not apply `G92` or redefine work coordinates after homing.

## Config

Gantry YAML defines:

- serial port
- gantry type (`cub` or `cub_xl`)
- CNC homing strategy
- total Z reference height
- Y-axis motion mode
- working volume
- optional `safe_z` (absolute deck-frame travel ceiling)
- optional GRBL settings expectations
- mounted instruments, offsets, reach depths, and driver settings

Representative example:

```yaml
serial_port: /dev/ttyUSB0
gantry_type: cub_xl
cnc:
  homing_strategy: standard
  total_z_range: 87.0
  y_axis_motion: head
  # Absolute deck-frame Z used for inter-labware travel and the entry
  # approach to the first well of a scan. Defaults to working_volume.z_max.
  safe_z: 85.0

working_volume:
  x_min: 0.0
  x_max: 399.0
  y_min: 0.0
  y_max: 280.0
  z_min: 0.0
  z_max: 87.0

grbl_settings:
  dir_invert_mask: 1
  status_report: 0
  homing_enable: true
  homing_dir_mask: 0

instruments:
  asmi:
    type: asmi
    vendor: vernier
    offset_x: 0.0
    offset_y: 0.0
    depth: 0.0
```

Use this file when:

- switching to a different gantry
- changing travel limits
- updating homing behavior
- recording expected controller settings
- changing mounted instruments, offsets, reach depths, or driver-specific connection settings

## CNC Fields

`gantry_type` is required at the gantry YAML root and identifies the physical
machine family. Supported values are `cub` and `cub_xl`. For `cub_xl`, setup
validation applies a built-in right X-max rail guard and rejects protocols whose
instrument point or known travel segment would hit the rail. A pose over the
rail is valid only when the instrument point is above the built-in rail height.

`homing_strategy` must be `standard`, which runs GRBL `$H`.

`total_z_range` is required and must be greater than zero. It describes the
configured vertical envelope. Deck labware deck-frame Z values come from
calibration anchors only — `calibration.a1.z` (plates / holders / tip racks)
or `location.z` (vials / holders). The labware `height` field is the
*physical outer dimension* (rim → underside) and is not a Z shorthand;
omitting an anchor `z` raises a load-time error.

`y_axis_motion` is optional and defaults to `head`. Use `head` when the gantry
head moves along Y, and `bed` when the machine bed moves along Y.

`safe_z` is optional and defaults to `working_volume.z_max`. It is the
absolute deck-frame Z used for inter-labware travel and the entry approach
for the first well of a scan. Validation requires every resolved approach
and action Z to satisfy `z <= safe_z` so the gantry can always retract
above the deck.

## Working Volume

Working volume bounds are inclusive and use the CubOS deck frame.

Protocol setup requires:

- `x_min: 0.0`
- `y_min: 0.0`
- non-negative `z_min`

Use [Calibrate Deck Origin](calibration.md) to measure the physical working
volume. The calibration script jogs to the front-left lower-reach origin, sets
X/Y with `G10 L20 P1 X0 Y0`, assigns Z by bottom contact or ruler gap, then
re-homes and reports the measured homed WPos as `(x_max, y_max, z_max)`.

For one-instrument bottom contact, use `z_min: 0.0`. For ruler-gap calibration,
use the measured gap as `z_min`. Example: if the TCP stops 5 mm above deck and
the homed WPos reads `Z=105`, use `z_min: 5.0`, `z_max: 105.0`.

Multi-instrument setups need per-instrument lower-reach limits and inactive-tool
collision checks instead of one global lower reach for every tool.

## Instrument Fields

Mounted instruments live under the gantry YAML `instruments` key.

- `offset_x` and `offset_y` describe XY offsets from the gantry/router
  reference point.
- `depth` is positive tool depth below the gantry reference point; in the +Z-up
  deck frame, gantry Z is computed as target/tool Z plus `depth`.

Instrument blocks carry only physical mounting state. Labware-relative
motion heights live on the protocol command — see "Protocol Height
Fields" below. Inter-labware and first-well-entry travel use the
gantry-level `safe_z`, not any instrument field.

## Protocol Height Fields

Labware-relative offsets above the calibrated well/labware surface Z
(positive = above; negative = below) are first-class arguments to the
protocol commands that consume them:

- `measurement_height` — required on `measure` and `scan`. It is the
  action plane offset.
- `interwell_scan_height` — required on `scan`. It is the between-wells
  XY-travel offset and must be at or above `measurement_height`.

Pipette commands (aspirate/dispense/etc.) engage at the labware reference
Z (well bottom, tip top) — i.e. `measurement_height = 0` implicitly.
- `park_position` is an explicit rest pose (absolute coords, not relative).
- ASMI `indentation_limit_height` is a *signed* labware-relative offset
  (mm above the well surface; negative = below). It must be at or below
  `measurement_height` (descent goes down).

Legacy names `entry_travel_z`, `entry_travel_height`,
`interwell_travel_height`, `safe_approach_height`, `indentation_limit`,
and ASMI `z_limit` are rejected before motion.

## Controller Bring-Up

Axis and homing normalization is controller administration, not routine
operator calibration. Use [Gantry Bring-Up](admin/gantry-bring-up.md) when a
machine is new or controller direction/WPos behavior is unknown.

That admin procedure covers:

- controller setting snapshots and rollback notes
- `$3` jog direction invert mask
- `$10` WPos status reporting
- `$23` homing direction invert mask
- WPos/MPos/WCO checks

## Supported Gantries

| Config | System | Current status |
|--------|--------|----------------|
| `configs/gantry/cub_xl_asmi.yaml` | CubOS-XL + ASMI | Measured deck-origin ASMI config from 2026-04-24; still requires staged hardware checks before broad reuse |
| `configs/gantry/cub_xl_sterling.yaml` | Sterling ASMI | Sterling ASMI setup; validate on hardware before real protocols |
| `configs/gantry/cub_filmetrics.yaml` | Cub + Filmetrics | Converted deck-origin starting point; recalibrate and hardware-validate before real Filmetrics runs |
| `configs/gantry/cub_xl_panda.yaml` | CubOS-XL + PANDA-style board | Estimated layout/config surface; placeholders require follow-up before real multi-instrument use |
