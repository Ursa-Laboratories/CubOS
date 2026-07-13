# 2026-04-16 — Remote ASMI Zoo Debugging

## Summary

Worked through running `Zoo` remotely on the Raspberry Pi over SSH port forwarding, then debugged multiple issues across `Zoo`, `CubOS`, GRBL controller settings, and the ASMI runtime path.

Main outcome:

- `Zoo` can run remotely on the Pi and be viewed locally through SSH port forwarding.
- Several failures were configuration or packaging issues rather than a single runtime bug.
- One real code fix was made in `CubOS`: remove GRBL soft reset (`Ctrl-X`) during connection verification because it was re-locking the controller into `Alarm`.

## What We Did

### Remote Zoo setup

- Confirmed `Zoo` runs as a server on the Pi and can be viewed locally with SSH port forwarding.
- Confirmed `npm` is required for `Zoo/frontend`.
- Confirmed Python backend dependencies are also required in the same Pi venv.

### Config-directory behavior

- Confirmed Zoo's `Browse` button opens a native directory picker on the machine running Zoo, not in the local browser.
- Identified `ZOO_CONFIG_DIR` as the clean way to point Zoo at a config directory on the Pi.
- Confirmed the frontend config directory field is read-only and cannot be typed into directly.

### CubOS packaging issue

- Found missing packaged data for deck labware definitions caused:
  `FileNotFoundError: .../deck/labware/definitions/registry.yaml`
- Recommended using editable `CubOS` install on the Pi as the immediate fix.

### ASMI_new vs CubOS config model

- Confirmed `ASMI_new` does not use the same `CubOS` gantry/deck/board/protocol YAML model.
- Confirmed `ASMI_new` hardcodes hardware geometry and runtime behavior in Python.
- Mapped the overlap conceptually, but not as interchangeable config files.

### Zoo/CubOS serial-race debugging

- Identified a Zoo-side serial access race:
  frontend position polling and protocol execution could touch the same serial port concurrently.
- Patched `Zoo/zoo/routers/protocol.py` locally to hold the serial lock during health check and protocol execution.
- Also made `Zoo/zoo/routers/gantry.py` connect flow more tolerant of initial coordinate-query failures.

These Zoo-side patches were diagnostic/supportive. The most important persistent machine-side fix was in `CubOS`.

### GRBL alarm / connect behavior

- Found that connecting through CubOS could re-trigger GRBL alarm immediately after homing.
- Traced the cause to the CubOS GRBL connect verification logic:
  `Ctrl-X` soft reset was being sent during `_verify_connection()`.
- Since GRBL had `$22=1`, soft reset dropped the controller back into homing lock / alarm state.
- Patched `CubOS/src/gantry/gantry_driver/driver.py` to remove `Ctrl-X` during connect verification while still waking the controller with `\r\n`.

This was the main runtime fix.

### GRBL mode / inversion debugging

- Collected GRBL settings and interpreted them.
- Confirmed:
  - `$10=1` meant `MPos`
  - `$10=0` meant `WPos`
  - `$3=1` meant X inverted only
- Switched temporarily between `MPos` and `WPos`.
- Switched temporarily between `$3=1` and `$3=0`.
- Restored original observed values at the end:
  - `$10=1`
  - `$3=1`

### Safety / recovery work

- Added direct GRBL helper scripts for status, unlock, reset-unlock, reporting-mode changes, and inversion changes.
- Used direct controller access because Zoo was not always in a healthy enough state to recover the machine safely.
- Noted at least one real mechanical incident on Y during homing/endstop interaction and paused software debugging to treat it as a hardware fault first.

## What We Learned

### About Zoo

- Zoo is a thin layer over CubOS. It does not have its own independent GRBL driver.
- The config-directory browser is local to the Pi session.
- Zoo displays user-facing coordinates, but protocol execution depends on the CubOS runtime and config values being internally consistent.

### About CubOS

- CubOS currently owns the real GRBL driver path used by Zoo.
- The controller connect path used legacy reset behavior that is not safe for current homing-lock workflows.
- The current coordinate translator does not flip X/Y at the gantry boundary. Only Z is inverted there in the present code.

### About GRBL

- The controller behavior depended heavily on:
  - `$10` status report mode
  - `$3` direction invert mask
  - `$22` homing enable
  - `$23` homing direction
- `Ctrl-X` during connect is unsafe when homing lock is enabled and the workflow expects the machine to remain homed/alive across reconnects.

### About config semantics

- Some gantry/deck issues came from mixing positive-display expectations with YAML/runtime constraints.
- Protocol execution failures were often due to invalid gantry YAML or missing dependencies, not protocol-step validation itself.
- ASMI deck/orientation behavior must be reasoned from calibration values and offsets, not comments alone.

### About ASMI_new

- `ASMI_new` does not soft-reset GRBL on connect.
- `ASMI_new` is `MPos`-first and derives work coordinates from `WCO` or internal offsets.
- That difference helps explain why `ASMI_new` could behave differently from `Zoo`/`CubOS` on the same machine.

## Files Added During This Session

- [grbl_recover.py](/Users/alexchan/Documents/hephaestus/scripts/grbl_recover.py:1)
- [grbl_set_wpos.py](/Users/alexchan/Documents/hephaestus/scripts/grbl_set_wpos.py:1)
- [grbl_set_mpos.py](/Users/alexchan/Documents/hephaestus/scripts/grbl_set_mpos.py:1)
- [grbl_report_mode.py](/Users/alexchan/Documents/hephaestus/scripts/grbl_report_mode.py:1)
- [grbl_set_x_not_inverted.py](/Users/alexchan/Documents/hephaestus/scripts/grbl_set_x_not_inverted.py:1)
- [grbl_restore_original_debug_settings.py](/Users/alexchan/Documents/hephaestus/scripts/grbl_restore_original_debug_settings.py:1)
- [patch_zoo_gantry_connect.py](/Users/alexchan/Documents/hephaestus/scripts/patch_zoo_gantry_connect.py:1)
- [grbl-setting-overrides.md](/Users/alexchan/Documents/hephaestus/docs/status/grbl-setting-overrides.md:1)

## Code Changed During This Session

- [CubOS/src/gantry/gantry_driver/driver.py](/Users/alexchan/Documents/hephaestus/CubOS/src/gantry/gantry_driver/driver.py:246)
  - Removed `Ctrl-X` soft reset from GRBL connect verification.

- [Zoo/zoo/routers/protocol.py](/Users/alexchan/Documents/hephaestus/Zoo/zoo/routers/protocol.py:143)
  - Added serial-lock coverage around gantry health check and protocol execution.

- [Zoo/zoo/routers/gantry.py](/Users/alexchan/Documents/hephaestus/Zoo/zoo/routers/gantry.py:145)
  - Made connect path more tolerant of initial position-query failure.

## Known Remaining Risks / Open Questions

- Need to confirm which Pi-side checkout / install path Zoo is actually importing:
  editable `~/CubOS` vs installed package in `~/Zoo/venv/.../site-packages`.
- Need to confirm whether the Zoo-side serial-lock and connect-tolerance changes should be committed permanently or only kept as local diagnostic patches.
- Need to confirm the intended final coordinate convention for the Cub-XL + ASMI combination:
  positive-space YAML vs negative-space legacy assumptions.
- Need to reconcile deck calibration comments vs actual coordinate values for ASMI.
- Need to confirm whether X inversion should really remain on the controller (`$3=1`) or be normalized in config / hardware instead.

## Recommended Next Time

1. Before touching Zoo, confirm the exact Python import paths on the Pi:
   `gantry.__file__` and `gantry.gantry_driver.driver.__file__`.

2. Keep a direct serial recovery path available before testing protocols:
   use the helper scripts in `scripts/`.

3. Start with controller state checks:
   - `$$`
   - `?`
   - report mode (`MPos` vs `WPos`)
   - alarm state

4. Validate the selected gantry YAML before running protocols:
   especially `working_volume` ordering and `total_z_height` vs `z_max`.

5. Validate sign conventions with one minimal jog and one minimal deck move before running full scan protocols.

6. If motion direction looks wrong, separate the problem into:
   - GRBL inversion (`$3`)
   - homing direction (`$23`)
   - deck calibration (`a1`, `a2`, `x_offset_mm`, `y_offset_mm`)
   - CubOS coordinate conversion

7. If the machine hits a stop or clanks mechanically, stop software debugging and treat it as a hardware recovery event first.
