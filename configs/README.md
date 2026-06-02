# CubOS Configs

The `configs/` tree is the current CubOS configuration surface. These files use
the deck-origin coordinate convention:

- origin `(0, 0, 0)` is the front-left-bottom reachable work volume
- protocol `home` preserves the calibrated persistent G54 WPos frame
- `+X` moves to the operator's right
- `+Y` moves away from the operator, toward the back of the gantry
- `+Z` moves up, away from the deck
- `-Z` moves down, toward the deck

Protocol, deck, gantry, and instrument code should speak only in this CubOS
deck frame. GRBL homing direction, raw MPos, WCO, and controller setting
details are admin/setup concerns documented in
`docs/admin/gantry-bring-up.md`.

`working_volume` is the usable deck/WPos range after homing pull-off. GRBL
`$130/$131/$132` and YAML `grbl_settings.max_travel_*` are controller
soft-limit spans and include `grbl_settings.homing_pull_off` (`$27`). A
machine with homed WPos `Z=91` and `$27=10` should save
`working_volume.z_max: 91` and `grbl_settings.max_travel_z: 101`.

## Directory Layout

```text
configs/
  gantry/     # Machine envelope, GRBL expectations, mounted instruments
  deck/       # Labware placement and calibration
  protocol/   # Ordered protocol steps
```

There are no separate instrument-board YAMLs. Mounted instruments and offsets live
inside the corresponding `configs/gantry/*.yaml` machine file. Protocol
motion heights live on the protocol command (see Height Semantics below).

## Runnable ASMI Example

```bash
PYTHONPATH=src python setup/validate_setup.py \
  configs/gantry/cub_xl_asmi.yaml \
  configs/deck/asmi_deck.yaml \
  configs/protocol/asmi_move_a1.yaml
```

For the full indentation protocol:

```bash
PYTHONPATH=src python setup/validate_setup.py \
  configs/gantry/cub_xl_asmi.yaml \
  configs/deck/asmi_deck.yaml \
  configs/protocol/asmi_indentation.yaml
```

## Current Files

- `gantry/cub_xl_asmi.yaml` - measured ASMI Cub-XL setup.
- `gantry/cub_xl_sterling.yaml` - Sterling ASMI setup.
- `gantry/cub_filmetrics.yaml` - Filmetrics setup with placeholder optical TCP
  values that still require hardware calibration.
- `gantry/cub_xl_panda.yaml` - PANDA estimate with placeholder camera/capper
  instrument entries; those placeholders parse as config data but will not
  instantiate until real instrument drivers are registered.
- `deck/asmi_deck.yaml`, `deck/sterling_deck.yaml`,
  `deck/filmetrics_deck.yaml`, `deck/panda_deck.yaml`,
  `deck/sharc_uv_deck.yaml`.
- `protocol/asmi_move_a1.yaml`, `protocol/asmi_indentation.yaml`,
  `protocol/sterling_park.yaml`, `protocol/sterling_vial_scan.yaml`,
  `protocol/filmetrics_scan.yaml`, `protocol/sharc_uv_curing_scan.yaml`,
  `protocol/sharc_uv_motion_scan.yaml`.

Offline-only fixtures live under `sim/` so they are not mistaken for measured
hardware setups. `sim/pipette_tip_transfer/` contains the gantry, deck, and
protocol triple used by `digital-sim` to replay pipette tip pickup, attached-tip
height, transfer, blowout, drop-tip, and home behavior without touching
hardware.

## Height Semantics

`measurement_height` and `interwell_scan_height` are **labware-relative
offsets** above the calibrated well/labware surface Z (positive = above,
negative = below). At runtime, action and approach planes are computed
as `well.z + offset`, where `well.z` is the calibration anchor's z (set
in the deck YAML). Both fields are first-class arguments to the
protocol command — instruments do not declare them. The plate's
``height`` is the physical outer dimension (rim → underside), used
for collision/visualization and for the ``well_depth <= height``
sanity check, not for motion math.

- `scan` requires `measurement_height` and `interwell_scan_height`
- `measure` requires `measurement_height`
- ASMI `indentation_limit_height` (top-level on `scan`): signed
  labware-relative offset (mm above the well surface; negative = below)
  for the deepest descent plane. Must be at or below `measurement_height`.
- gantry `safe_z`: absolute deck-frame Z used for inter-labware travel
  (the only absolute Z in the engagement path)

Pipette commands default to the labware reference Z (`height = 0`), but
liquid-handling commands may set `height`, or `source_height` /
`destination_height` for transfers. `pick_up_tip` must target a `tip_rack`
slot; when `tip_length` is omitted, CubOS defaults to 59.3 mm for the current
Opentrons 300 uL tips. Validation adds that extension to active pipette depth
for safe_z and action-Z bounds until `drop_tip`.
Unrecognized scan fields are rejected at protocol-load time by the command's
Pydantic schema.

`scan.plate` can target a top-level `WellPlate` or a nested holder path such
as `plate_holder.plate`. The SHARC UV config uses this nested form.

Use `protocol/sharc_uv_motion_scan.yaml` for SHARC gantry scan bring-up when
you need the same 96-well motion path without issuing UV cure commands.

## Validation Status

Offline setup validation is useful for schema, bounds, and protocol semantics,
but it does not prove safe real motion. Before running any hardware protocol,
verify GRBL `$3`, `$10`, `$20`, `$22`, `$23`, `$27`, `$130`, `$131`, and
`$132`, home to the expected back-right-top corner, jog each positive axis, and
run `setup/calibrate_gantry.py` for the active machine/TCP.
