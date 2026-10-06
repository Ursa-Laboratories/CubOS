# Polar Bear 4040-PRO MAX bring-up

## Current branch and station

- Branch: `polar-nano-modules`
- Pi: `polar@192.168.2.2`
- Pi repository: `/home/polar/CubOS`
- Live config: `/home/polar/cubos-data/configs/gantry/polar-bear-4040.yaml`
- Machine: Genmitsu 4040-PRO MAX
- Calibrated CubOS usable volume: X 0–259.514, Y 0–380.388,
  Z 4.558–84.558 mm, with a 10 mm homing pull-off

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
- The gantry calibration wizard was subsequently completed and saved. Live
  offsets are pipette `(94.7, -2.5, depth 0)`, camera and lighting
  `(195.357, -29.195, depth -87.321)`, and capper
  `(0, 0, depth -32)`. The capper engagement depth remains `0` pending its
  dedicated physical setup.
- Fixed the Operator **New** deck action so it creates an empty working deck
  instead of leaving labware creation disabled. Added calibration templates
  for the existing 9-position 20 mL and 12-position 4 mL vial racks and for
  tip disposal. The updated picker now offers Tip rack, Well plate, Vial,
  Vial rack / grid, and Tip disposal.
- Calibrating an item on a new deck now keeps the result in the browser
  working copy until the operator enters a deck filename and clicks **Save**;
  it no longer risks writing a file named `unsaved`.
- The calibrated contact-angle deck is now saved as
  `contactangle_deck.yaml` with `ursa_wellplate`, `tip_disposal_1`,
  `tip_rack_green`, and `vial_rack` entries. A draft protocol was saved as
  `contactangle_protocol.yaml`. Its sole step is currently `pick_up_tip` at
  `tip_rack_green.A1`; setup validation passes. The protocol has not been run.
- Pre-deployment config backups for those UI changes are at
  `/home/polar/cubos-data/backups/configs-before-labware-ui-20261002-222352`
  and
  `/home/polar/cubos-data/backups/configs-before-new-deck-fix-20261002-222707`.
  The follow-up unsaved-deck fix backup is at
  `/home/polar/cubos-data/backups/configs-before-unsaved-deck-fix-20261002-223129`.

## Offline validation

- Gantry schema, domain-model, and machine-geometry tests: 85 passed.
- Operator `GantryEditor` tests: 25 passed.
- Operator TypeScript build and Vite production build passed locally and on
  the Pi.
- Operator App, Deck editor, and labware-calibration tests: 100 passed locally;
  the focused 22-test Deck editor suite also passed on the Pi.
- Both the tracked and live Polar Bear YAML load as
  `genmitsu_4040_pro_max` with no built-in fixed structures.
- The Polar branch now exposes the existing no-state `dispense` operation as
  a YAML protocol command. The contact-angle A1 workflow is staged at
  `examples/polar-bear/protocol/contact-angle-a1.yaml`; 154 focused command,
  registry, tip-state, and motion-bounds tests pass locally and on the Pi.
  The change is deployed at Pi commit `77366e8c`, and the workflow is saved as
  `/home/polar/cubos-data/configs/protocol/contact_angle_a1.yaml`. The existing
  `contactangle_protocol.yaml` was preserved. The pre-deployment live-config
  backup is
  `/home/polar/cubos-data/backups/configs-before-contact-angle-protocol-20261003-173042`.

## Physical validation pending

Do not run a protocol until the saved deck calibration has been checked
against the physical labware and the complete protocol passes setup validation.

- The powered homing attempt moved X left and Y forward while Z moved upward.
  CubOS requires `$H` to move toward back-right-top. The confirmed correction
  is `$23=0`, reversing X/Y homing while preserving the correct Z direction.
- The light Nano moved from hub port `1.3` to `1.1`; `ID?` confirmed
  `/dev/ttyUSB1=LIGHT_MODULE`. The cap Nano remains on hub port `1.4`, with
  `ID?` confirming `/dev/ttyUSB2=CAP_MODULE`. The Picus by-id path and FLIR
  camera enumeration are unchanged.
- Verify the saved rack/plate models, pitches, and recorded positions against
  the physical parts before the first run. Do not substitute the 20 mL
  vial-rack template for a 4 mL rack or vice versa.
- Complete `contactangle_protocol.yaml` beyond its one-step pickup draft and
  run setup validation again before considering a physical run.
- The live `contactangle_deck.yaml` now defines `vial_rack` as a capped
  `vial_grid` for 5 mL vials (`76 mm` tall, `27 mm` diameter), preserving its
  calibrated positions and pitches. Its tip rack now uses the operator's
  measured `25 mm` tip length instead of `59.3 mm`. The deck backup before
  conversion is
  `/home/polar/cubos-data/backups/contactangle_deck-before-vial-grid-20261003-174313.yaml`.
- For empty-deck commissioning only, the live pipette depth was changed from
  the uncalibrated `0.0` default to provisional `-25.0 mm`, making the
  attached 25 mm tip's net depth zero in CubOS coordinates. The prior gantry
  config is backed up at
  `/home/polar/cubos-data/backups/polar-bear-4040-before-provisional-pipette-depth-20261003-174514.yaml`.
  This depth must be physically calibrated before running with labware.
- With `polar-bear-4040.yaml`, `contactangle_deck.yaml`, and
  `contact_angle_a1.yaml`, setup validation now passes with no errors after a
  CubOS service restart. No homing, jogging, or protocol movement was
  performed while applying these corrections.
- The capper was centered over capped `vial_rack.A1` and lowered until its
  magnet face touched the cap at gantry `(96.274, 372.680, 38.390)`. Against
  the saved vial target `(96.210, 371.895, 71.428)` and capper depth `-40.0`,
  the measured contact setting is `engage_depth_mm: 6.962`. The operator
  subsequently chose to retain capper XY offsets `(0.0, 0.0)`; setup
  validation passes with those final values. The pre-calibration gantry
  config is backed up at
  `/home/polar/cubos-data/backups/polar-bear-4040-before-capper-calibration-20261006-184432.yaml`.
  The intermediate nonzero-XY config is backed up at
  `/home/polar/cubos-data/backups/polar-bear-4040-before-capper-xy-reset-20261006-184540.yaml`.
  A controlled cap sensor/magnet test is still required before relying on a
  complete physical decap/cap cycle.

## Plate relocation and camera alignment (2026-10-06)

- The operator physically moved the well plate before centering the camera on
  A1 and A2. The observed gantry positions were A1 `(35.274, 97.718, 73.390)`
  and A2 `(35.274, 85.218, 73.390)`.
- Both observations preserve the expected 12.5 mm A1-to-A2 pitch. Using the
  independently calibrated camera mount offset `(195.357, -29.195)` places
  the relocated plate at A1 `(230.631, 68.523, 6.186)` and A2
  `(230.631, 56.023, 6.186)`.
- A provisional edit had incorrectly absorbed the plate translation into the
  camera and lighting offsets. That edit was corrected: camera and lighting
  XY offsets are restored to `(195.357, -29.195)`, while the new A1/A2 values
  are saved in `contactangle_deck.yaml`. Other deck entries were preserved.
- The pre-correction live gantry and deck files are backed up at
  `/home/polar/cubos-data/backups/plate-move-correction-20261006-182140`.
- CubOS was refreshed after the correction and showed the new plate values.
  The gantry remained connected and Idle; no home, jog, or protocol command
  was issued.
- The operator then confirmed sharp focus over relocated A1 at gantry
  `(35.274, 97.718, 67.390)`. With camera depth `-62.321` and well surface Z
  `6.186`, the corresponding labware-relative `image_height` is `123.525 mm`.
  The operator subsequently chose `image_height: 125` as the start of each
  ten-plane curvature stack (`0.2 mm` steps, ending at `123.2 mm`); the plane
  nearest the confirmed focus is `123.6 mm`. Both live `image_well` steps and
  the tracked example use the `125 mm` start. Setup validation passes for all
  eight live protocol steps. The preceding live protocol is backed up at
  `/home/polar/cubos-data/backups/contact-angle-before-focus-height-20261006-183736.yaml`.

## GRBL Z-ceiling clearance (2026-10-06)

- The first XY travel attempted `G01 Z84.558 F3000.0`, exactly equal to the
  configured Z maximum, and GRBL raised `ALARM:2`. Displayed WPos and the
  controller's internal machine-coordinate precision can differ at that
  boundary.
- Multi-tool XY travel now keeps the carriage `0.5 mm` below the configured
  ceiling. On this station the travel command becomes Z `84.058`; hover,
  action, and configured `safe_z` targets are otherwise unchanged.
- Focused Pi validation: `50 passed` in
  `packages/core/tests/gantry/test_instrument_mount.py`. The pre-deployment
  source and test are backed up at
  `/home/polar/cubos-data/backups/z-ceiling-fix-20261006-185100`.
- The failed protocol was inactive before deployment. No unlock, home, jog,
  resume, instrument actuation, or protocol command was issued.
- A one-step live validation protocol was created at
  `protocol/z_ceiling_camera_test.yaml`; it performs one standard white-light
  image of relocated A1 and passes setup validation. The first reconnect
  attempt after the alarm blocked waiting for the GRBL serial connection, so
  physical validation stopped before homing or executing the test. The hung
  client was cleared and CubOS was left active with the gantry disconnected;
  the controller requires a physical power cycle before another connection
  attempt.
- After the operator power-cycled the gantry, a fresh CubOS process still
  received no response to a bounded 45-second connect attempt. The stable
  `/dev/serial/by-path/...0:2...` link remained present, but GRBL did not
  answer. CubOS was restarted to clear the blocked connection handler and
  left active with no run and the gantry disconnected. No homing or camera
  test motion occurred. Check the CNC main power, emergency-stop state, and
  controller-side USB/power connections before retrying.

- A later reconnect and back-right-top home succeeded. The one-step camera
  test then cleared the original upper boundary and reached A1 XY, confirming
  the `84.058 mm` ceiling clearance. Before imaging, however, `image_well`
  used the shared instrument `safe_z` (`78 mm`) as a camera approach plane.
  The camera depth `-62.321 mm` transformed that into carriage Z `15.679 mm`.
  The physical lower Z switch asserted at WPos Z `17.404 mm` (`Pn:Z`) and the
  controller stopped with `ALARM:3`; no image or instrument action occurred.
- `image_well` now uses the high multi-tool carriage clearance for its first
  XY transit and final retract. For this station that means carriage Z
  `84.058 mm`, followed by the calibrated A1 imaging position near carriage Z
  `68.865 mm`; it never visits the low shared `safe_z` plane. Focused testing
  in a temporary Pi checkout passes: `30 passed` in
  `packages/core/tests/protocol_engine/test_camera_commands.py`. Deployment
  and the repeat camera-only hardware test are pending after the operator
  clears the active lower-limit condition.

Before the next homing test, clear the full travel area, keep a hand at the
gantry power switch, connect through CubOS, verify live `$23=0`, and stop
immediately if any axis moves away from back-right-top.

For deck calibration, use the pipette as the reference instrument and follow
the wizard one item at a time. Save the new deck YAML before leaving the Deck
tab; unsaved labware exists only in the browser working copy.
