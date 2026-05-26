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

## Directory Layout

```text
configs/
  gantry/     # Machine envelope, GRBL expectations, mounted instruments
  deck/       # Labware placement and calibration
  protocol/   # Ordered protocol steps
```

There are no separate board YAMLs. Mounted instruments and offsets live
inside the corresponding `configs/gantry/*.yaml` machine file. Protocol
motion heights live on the protocol command (see Height Semantics below).

## Sample ASMI Examples

Tracked files under `configs/` are samples only. Active operator/lab configs
live in the sibling BU-Configs repository or another config directory selected
by the operator.

The gantry folder keeps one sample per supported machine family:

- `gantry/cub.sample.yaml` - Cub + ASMI, seeded with `total_z_range: 80.0`.
- `gantry/cub_xl.sample.yaml` - Cub XL + ASMI, seeded with
  `total_z_range: 110.0`.

The deck and protocol folders keep matching ASMI defaults:

- `deck/asmi_deck.sample.yaml` - ASMI 96-well plate deck-origin sample.
- `protocol/asmi_indentation.sample.yaml` - ASMI indentation scan sample.

Copy sample files before editing machine-specific values.

Validate the Cub sample set:

```bash
PYTHONPATH=src python setup/validate_setup.py \
  configs/gantry/cub.sample.yaml \
  configs/deck/asmi_deck.sample.yaml \
  configs/protocol/asmi_indentation.sample.yaml
```

Validate the Cub XL sample set:

```bash
PYTHONPATH=src python setup/validate_setup.py \
  configs/gantry/cub_xl.sample.yaml \
  configs/deck/asmi_deck.sample.yaml \
  configs/protocol/asmi_indentation.sample.yaml
```

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

Pipette commands engage at the labware reference Z (well bottom, tip
top) — `measurement_height = 0` implicitly. Unrecognized scan fields are
rejected at protocol-load time by the command's Pydantic schema.

`scan.plate` can target a top-level `WellPlate` or a nested holder path such
as `plate_holder.plate`. The SHARC UV config uses this nested form.

Use `protocol/sharc_uv_motion_scan.yaml` for SHARC gantry scan bring-up when
you need the same 96-well motion path without issuing UV cure commands.

## Validation Status

Offline setup validation is useful for schema, bounds, and protocol semantics,
but it does not prove safe real motion. Before running any hardware protocol,
verify GRBL `$3`, `$10`, `$20`, `$22`, `$23`, `$130`, `$131`, and `$132`, home
to the expected back-right-top corner, jog each positive axis, and run
`setup/calibrate_gantry.py` for the active machine/TCP.
