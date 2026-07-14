# Troubleshooting & Recovery

## GRBL Alarm States

GRBL enters an **alarm state** after a hard-limit trip, an unexpected
disconnect/reset, or certain startup conditions. While in alarm, GRBL
refuses motion commands until it's cleared.

CubOS already recovers automatically in the two places most likely to hit
this:

- **During calibration jogging**, a hard-limit trip triggers a soft reset,
  `$X` unlock, and a small pull-off opposite the jog that caused it (see
  [Calibration: Jog Controls](calibration.md#jog-controls)).
- **At the start of a protocol run**, if the gantry is already in alarm,
  CubOS unlocks it before proceeding and raises an error if it can't get a
  clean status afterward.

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
