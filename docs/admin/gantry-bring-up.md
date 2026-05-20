# Gantry Bring-Up

This admin page is for controller setup before normal deck-origin calibration.
Use it when a machine is new, controller settings are unknown, homing direction
is wrong, or WPos/MPos behavior has not been recorded.

For normal operator calibration after the controller is already normalized, use
[Calibrate Deck Origin](../calibration.md).

## Target Behavior

CubOS expects the controller and WPos frame to match the deck frame used by
protocols:

- `$H` homes to the back-right-top machine corner
- `+X` jogs right from the operator perspective
- `+Y` jogs back, away from the operator
- `+Z` jogs up, away from the deck
- GRBL status reports WPos for CubOS runtime reads

The gantry boundary does not apply a hidden Z sign flip. Controller settings
and work-coordinate calibration must make WPos match the CubOS deck frame.

## Snapshot First

Before changing settings, save the current controller state and a rollback note.

```text
$$
?
```

Record at least:

- `$3` direction invert mask
- `$10` status report mode
- `$23` homing direction invert mask
- homing enable and hard/soft limit settings
- raw status line showing WPos or MPos
- whether WCO appears in status after a few `?` queries

If any value is changed, write down the original value and the reason for the
change before continuing.

## Status Reporting

CubOS expects WPos reporting during normal operation. `$10=0` is the expected
GRBL status-report mode for WPos:

```text
$10=0
```

After setting it, query status:

```text
?
```

The status line should include `WPos:`. If the controller reports `MPos:`,
capture WCO behavior before debugging CubOS. GRBL defines the relationship as:

```text
MPos = WPos + WCO
```

## Homing Direction

Run homing only when the tool is clear of fixtures, stock, samples, and cables.
Keep a hand on the E-stop or controller reset.

```text
$H
```

The target homing corner is back-right-top. If homing goes to the wrong corner,
adjust `$23`.

GRBL bitmask values:

```text
X = 1
Y = 2
Z = 4
```

Example: invert X and Y homing.

```text
$23=3
```

Run `$H` again after each `$23` change. Stop if any axis heads toward a hard
collision.

## Jog Direction

After homing reaches back-right-top, jog each axis slowly and confirm physical
direction:

- `+X` moves right
- `+Y` moves back
- `+Z` moves up

If jogging direction is wrong, adjust `$3` with the same GRBL bitmask:

```text
$3=2
```

`$3` and `$23` interact. After changing `$3`, run `$H` again and re-check
homing direction.

Repeat until both are true:

- `$H` always homes to back-right-top
- positive jogs move right, back, and up

## Save Expected Settings

Save the final controller expectations in the gantry or board config used by
the machine. For example:

```yaml
grbl_settings:
  dir_invert_mask: 2
  status_report: 0
  homing_enable: true
  homing_dir_mask: 3
```

Use the exact values measured on the machine, not these example values.

## Rollback Notes

For each setting changed, record:

- original value
- new value
- date
- machine/controller
- operator
- reason for the change
- how to restore the original value

Example:

```text
2026-04-28 Cub XL ASMI
$23: 0 -> 3
Reason: normalize homing to back-right-top.
Rollback: send $23=0, then re-home and re-check jog directions.
```

## Hand Off To Calibration

Once homing, jog direction, and WPos reporting match the target behavior, run
the operator calibration tutorial:

```bash
PYTHONPATH=src python setup/calibrate_gantry.py configs/gantry/cub_xl_asmi.yaml
```

Do not run protocols on a real setup until deck-origin calibration and minimal
hardware validation pass.
