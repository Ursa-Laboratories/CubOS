# Troubleshooting & Recovery

## GRBL Alarm States

GRBL enters an **alarm state** after a hard-limit trip, an unexpected
disconnect/reset, or certain startup conditions. While in alarm, GRBL
refuses motion commands until it's cleared.

CubOS handles these cases as follows:

- CLI calibration can attempt one directed reset/unlock and pull-off after a
  failed jog. It does not repeat the move or reset after a failure.
- An open Operator calibration wizard attempts one automatic backoff for an
  eligible fault tied to its own accepted single-axis jog. Fresh controller
  state must confirm only that axis's switch. Foreign/unknown jogs, a reopened
  wizard, Stop/close and failed attempts do not trigger automatic movement.
  Outside calibration, **Pull off limit** remains explicit. **Manual pull-off**
  requires an explicitly confirmed axis and away direction. Every recovery
  leaves **Home required** until successful explicit homing.
- At protocol startup, the CLI can clear an expected startup alarm and checks
  the resulting controller state before continuing.

If you're driving the controller directly (a serial terminal, not a CubOS
script) — for example during [Gantry Bring-Up](admin/gantry-bring-up.md) —
clear an alarm manually:

```text
$X
```

`$X` clears the alarm flag but does **not** re-verify machine position. GRBL
can still consider itself positioned correctly when it isn't.

!!! warning "Re-home after any alarm"
    Send `$H` again after clearing an alarm, before trusting WPos or running
    anything that assumes a known position. This includes: any hard-limit
    trip, a controller power cycle, or a manual `$X` unlock. Do not resume a
    protocol or continue calibration on unverified position.

## Stuck on a Limit Switch

If the gantry stops with an axis pressing a limit switch — a jog overran
into the hard limit, or the machine was powered off in that position — it
can look bricked: GRBL boots in alarm, refuses to home (homing would drive
further into the switch), and rejects jogs.

An eligible wizard-owned calibration jog triggers one automatic guarded
backoff. Otherwise, use **Pull off limit** explicitly when CubOS still knows the
original accepted jog and verifies the matching active switch. This sends one
reset/unlock and one 5 mm reverse jog at 100 mm/min. It does not automatically
home, resume jogging, or retry a failed recovery.

After a restart, that original jog may be unknown. **Manual pull-off** allows
one 1 mm jog at 100 mm/min only after you explicitly select the active axis,
choose the direction away from the switch, and confirm the path is clear. The
software verifies the switch again before the move; it cannot infer which end
of the axis is pressed. Do not guess the direction.

Use **Stop** to cancel. Neither mode disables limits, zeroes coordinates, or
automatically repeats a rejected move. If the controller refuses the jog,
multiple inputs are active, or the direction is uncertain, stop and inspect
the machine. Clear the instrument head, fixtures, and cables before explicitly
homing once the switch is released.

Do not run protocols or continue calibration until homing succeeds — see
the warning above about trusting position after an alarm.

## Controller Drops Off USB at a Limit Trip

Some controller boards brown out their USB bridge when a hard-limit trip
halts the steppers — the board reboots and re-enumerates on the bus, and
every command afterward times out on the stale connection ("Unlock ($X)
timed out waiting for ok", position reads failing).

A connection loss stops recovery; CubOS does not reconnect and resume a
pull-off automatically. Check controller power, the USB cable, and its strain
relief. Reconnect only after inspecting the machine. The position reference
remains unverified until you explicitly home successfully.

## After a Physical Crash

1. **Stop.** Release the jog control immediately (or send `Q`/abort in the
   CubOS script you're running). If the gantry is still moving, hit the
   E-stop.
2. **Clear the alarm.** Power-cycle the controller, or soft-reset and send
   `$X` if you're on a direct serial terminal.
3. **Re-home.** Run `$H` (or the CubOS script's homing step). Never trust
   WPos after a crash without re-homing first.
4. **Re-verify calibration.** A crash can shift the calibration reference,
   labware, or stress a mount out of alignment. If there's any doubt, redo
   calibration (below) rather than resuming on old calibrated values.
5. Only resume protocols once homing and the
   [interactive jog test](calibration.md#interactive-jog-test) both pass
   again.

## Port Busy / Permission Denied

A serial port can only be held open by one program. If CubOS can't connect:

- **Linux:** `Permission denied` on `/dev/ttyUSB*` means your user isn't in
  the `dialout` group — add it, then log out and back in:
  ```bash
  sudo usermod -aG dialout $USER
  ```
  A port that connects but immediately errors is usually already held open
  by another process — check with:
  ```bash
  lsof /dev/ttyUSB0
  ```
- **macOS:** same idea as Linux — check what's holding `/dev/tty.*` open:
  ```bash
  lsof /dev/tty.usbserial*
  ```
- **Windows:** `COM port already in use` / `Access is denied` almost always
  means another program has it open — close Candle, Universal Gcode Sender,
  the Arduino IDE serial monitor, or any other terminal connected to that
  port, then retry. Confirm the port number hasn't changed in Device
  Manager → Ports (COM & LPT).

This is the same conflict the calibration
[warning about closing other GRBL software](calibration.md#before-you-start)
covers — one program on the port at a time.

## Redo Calibration From Scratch

Calibration doesn't write to a separate data store — it writes calibrated
values (working volume, offsets, GRBL travel settings) directly back into
the gantry YAML you point it at, either overwriting the input file or, with
`--output-gantry`, into an explicit copy. Calibrated gantry configs live
wherever you keep your gantry YAML, typically `packages/core/configs/gantry/`.

To start clean:

- If you calibrated with `--output-gantry`, just re-run calibration — the
  original input file was never modified.
- If you calibrated in place and want to discard the result, restore the
  file from version control:
  ```bash
  git checkout -- packages/core/configs/gantry/<your-gantry-file>.yaml
  ```
- Then re-run [Calibration](calibration.md) from the top.
