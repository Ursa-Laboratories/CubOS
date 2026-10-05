# Polar Bear 4040-PRO MAX bring-up

## Current branch and station

- Branch: `polar-nano-modules`
- Pi: `polar@192.168.2.2`
- Pi repository: `/home/polar/CubOS`
- Live config: `/home/polar/cubos-data/configs/gantry/polar-bear-4040.yaml`
- Machine: Genmitsu 4040-PRO MAX with 400/400/80 mm GRBL travel
- CubOS usable volume: 390/390/70 mm, reserving the configured 10 mm
  homing pull-off

## Completed

- Added dedicated Nano text-serial lighting and capper drivers.
- Recorded the Polar Bear station config and stable USB paths.
- Added the distinct `genmitsu_4040_pro_max` gantry type. It does not inherit
  the PROVerXL 4030 / Cub XL right-rail collision geometry.
- Updated the Operator gantry editor to show `Genmitsu 4040-PRO MAX`.
- Backed up the pre-change live config at
  `/home/polar/cubos-data/backups/configs-before-4040-type-20261002-170532`.
- Deployed the new type to the Pi and restarted `cubos`; the service returned
  healthy with no active protocol and the gantry disconnected.
- After confirming that the earlier home moved X left, Y forward, and Z up,
  changed the tracked and live homing mask to `$23=0`. The controller setting
  was written through the CubOS GRBL-settings API and read back as `$23=0`.
  `$27` read back as the expected `10`; reconnect returned `Idle` with no
  calibration warning and no active protocol. No homing or jog command was
  issued while applying these settings.
- Updated the light path to hub port `1.1` after `ID?` identified
  `/dev/ttyUSB1` as `LIGHT_MODULE`; `/dev/ttyUSB2` still identified as
  `CAP_MODULE` on hub port `1.4`.
- Added the Linux Aravis 0.8 backend for the Point Grey/FLIR camera because
  Spinnaker/PySpin does not support the station's Python 3.13 runtime. The Pi
  has `gir1.2-aravis-0.8`, `python3-opencv`, and `python3-numpy` installed,
  plus a persistent `video`-group udev rule for USB vendor `1e10`.
- Changed only the Polar Bear camera backend from `pyspin` to `aravis`. The
  pre-change live config tree is backed up at
  `/home/polar/cubos-data/backups/configs-before-aravis-20261002-214417`.
  The Pi clock is stale, so that directory timestamp predates the actual
  2026-10-05 deployment date.
- Captured a hardware frame from the Grasshopper3 GS3-U3-32S4C at 2048x1536,
  and confirmed the Operator calibration wizard now displays a live preview.
  Focused camera tests pass on the Pi: 41 passed.
- Restarting CubOS preserved the open browser wizard's recorded pipette and
  capper values. Restoring server-side calibration mode through
  `prepare-origin` also performed the endpoint's built-in homing cycle. The
  gantry ended Idle at X 259.514, Y 380.388, Z 84.558 with calibration mode
  active. No subsequent jog or protocol movement was issued.

## Offline validation

- Gantry schema, domain-model, and machine-geometry tests: 85 passed.
- Operator `GantryEditor` tests: 25 passed.
- Operator TypeScript build and Vite production build passed locally and on
  the Pi.
- Both the tracked and live Polar Bear YAML load as
  `genmitsu_4040_pro_max` with no built-in fixed structures.

## Physical validation pending

Do not run a protocol or continue deck calibration yet.

- The powered homing attempt moved X left and Y forward while Z moved upward.
  CubOS requires `$H` to move toward back-right-top. The confirmed correction
  is `$23=0`, reversing X/Y homing while preserving the correct Z direction.
- The light Nano moved from hub port `1.3` to `1.1`; `ID?` confirmed
  `/dev/ttyUSB1=LIGHT_MODULE`. The cap Nano remains on hub port `1.4`, with
  `ID?` confirming `/dev/ttyUSB2=CAP_MODULE`. The Picus by-id path and FLIR
  camera enumeration are unchanged.
- The pipette and capper are marked recorded in the still-open browser wizard,
  but the wizard has not reached its final save step. The live YAML therefore
  still contains zero instrument offsets/depths. Do not refresh, reset, or
  close that wizard before completing and saving calibration.
- Camera centering and its distance-from-block value remain to be recorded.

Before the next homing test, clear the full travel area, keep a hand at the
gantry power switch, connect through CubOS, verify live `$23=0`, and stop
immediately if any axis moves away from back-right-top.

For the current calibration session, use only the wizard jog controls to move
the camera from home back over the calibration block mark. Confirm the live
preview is centered, enter the measured distance from the camera to the top of
the block, and click **Record camera**. Continue through the wizard and use its
final save action so the recorded pipette, camera, capper, and copied lighting
offsets are written to the live YAML.
