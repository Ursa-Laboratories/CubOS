# Gantry Bring-Up

Use this page only when the controller itself needs first-time setup: a new
machine, unknown GRBL settings, wrong homing direction, wrong jog direction, or
status lines that do not report `WPos`.

If you bought a pre-configured device through [ursalabs.ai](https://ursalabs.ai),
this should already be done. Go straight to [Calibration](../calibration.md).

Bring-up uses [Universal Gcode Sender (UGS)](https://github.com/winder/Universal-G-Code-Sender)
connected directly to the controller. Do not use CubOS for this page.

!!! warning "This moves real hardware"
    Clear the deck, keep cables out of the travel path, and keep a hand near
    the E-stop or controller reset. Stop immediately if an axis moves toward a
    collision.

## Goal

At the end of bring-up, the controller must match the CubOS deck frame:

- `$H` homes to the back-right-top corner.
- Jogging `+X` moves right from the operator perspective.
- Jogging `+Y` moves back, away from the operator.
- Jogging `+Z` moves up, away from the deck.
- GRBL status reports `WPos:`, not `MPos:`.

CubOS does not hide or flip these directions in software. The controller
settings must make the reported work position match the physical deck.

![CubOS deck coordinate frame shown on the gantry](../images/orientation.webp){ width="520" }

## Connect With UGS

1. Open UGS.
2. Select the controller serial port from the dropdown near the top of the
   window.
   - Windows ports look like `COM3`, `COM4`, etc.
   - macOS ports look like `/dev/tty.usbserial-XXXX` or
     `/dev/tty.usbmodemXXXX`.
   - If you are not sure which one is the controller, unplug the USB cable,
     reopen the dropdown, and look for the port that disappeared.
3. Set the baud rate to `115200`.
4. Click **Connect**.

To send a command, type it into the command line at the bottom of UGS and press
Enter. GRBL replies `ok` after it accepts the command.

To jog, use the UGS jog panel. Use a small step size while checking directions.

## Save The Current Settings

Before changing anything, copy the current controller settings and status into
your setup notes:

```text
$$
?
```

Record these values:

- `$3` direction invert mask
- `$23` homing direction invert mask
- `$10` status report mode
- `$27` homing pull-off distance
- `$22` homing enable
- `$20` soft limits
- `$21` hard limits
- the status line, especially whether it shows `WPos:` or `MPos:`

For every value you change, write down the old value, new value, date, machine,
operator, and reason. Example:

```text
2026-04-28 Cub XL ASMI
$23: 0 -> 3
Reason: normalize homing to back-right-top.
Rollback: send $23=0, then re-home and re-check jog directions.
```

## Set WPos Reporting

CubOS expects GRBL status lines to report work position (`WPos`). Set:

```text
$10=0
```

Then query status:

```text
?
```

The response should contain `WPos:`:

```text
<Idle|WPos:0.000,0.000,0.000|FS:0,0>
```

If it still shows `MPos:`, send `$10=0` again and query `?` again before
continuing.

## Fix Jog And Homing Direction

Two GRBL settings control the direction behavior:

- `$3` controls which way each axis moves during normal jogging and motion.
- `$23` controls which way each axis moves during homing.

Both settings use the same axis values:

```text
X = 1
Y = 2
Z = 4
```

To invert more than one axis, add the values together. For example, X + Y is
`1 + 2 = 3`, so the command is `$3=3` or `$23=3`.

### 1. Check Jog Direction

Use a small UGS jog step and check one axis at a time:

| Jog problem | Change |
|---|---|
| `+X` moves left instead of right | Toggle X bit `1` in `$3` |
| `+Y` moves toward the operator instead of back | Toggle Y bit `2` in `$3` |
| `+Z` moves down instead of up | Toggle Z bit `4` in `$3` |

Example: if `$3=0` and only `+Y` is wrong, set:

```text
$3=2
```

Repeat until positive jogs move right, back, and up.

### 2. Check Homing

After jogging is correct, run homing:

```text
$H
```

The target homing corner is back-right-top. If homing heads toward the wrong
end of an axis, stop and toggle that axis in `$23`.

| Homing problem | Change |
|---|---|
| X homes left instead of right | Toggle X bit `1` in `$23` |
| Y homes front instead of back | Toggle Y bit `2` in `$23` |
| Z homes down instead of up | Toggle Z bit `4` in `$23` |

Example: if `$23=0` and X and Y home in the wrong directions, set:

```text
$23=3
```

Run `$H` again after each `$23` change. Do not continue until homing reliably
goes to back-right-top.

If you change `$23`, jog again afterward. `$3` and `$23` affect the same
physical axes, so changing one can reveal that the other also needs an
adjustment.

Repeat until both checks pass:

- `$H` always homes to back-right-top.
- Positive jogs move right, back, and up.

## Set Homing Pull-Off

`$27` is how far GRBL backs away from a limit switch after homing. The normal
bring-up value is:

```text
$27=10
```

You do not need to copy `$27` into the gantry YAML by hand. During calibration,
CubOS reads the live `$27` value and writes it into the output gantry YAML as
`grbl_settings.homing_pull_off`.

Calibration also keeps this pull-off distance outside the usable deck range.
For example, if homed WPos Z is `91` and `$27=10`, the deck
`working_volume.z_max` is `91`, while controller `max_travel_z` is `101`.

## Final Checklist

Before leaving UGS, confirm:

- `?` reports `WPos:`.
- `$H` homes to back-right-top.
- `+X` jogs right.
- `+Y` jogs back, away from the operator.
- `+Z` jogs up.
- Your setup notes include the original and final values for `$3`, `$23`,
  `$10`, and `$27`.

Then close UGS. The serial port can only be used by one program at a time, so
UGS must be closed before running CubOS calibration.

Continue to [Calibration](../calibration.md). Do not run real protocols until
deck-origin calibration and the minimal hardware validation steps pass.
