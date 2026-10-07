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
- The fix was deployed after backing up the previous live camera command and
  test at
  `/home/polar/cubos-data/backups/camera-clearance-fix-20261006-193000`.
  The live focused test again passed (`30 passed`). The operator-authorized
  recovery home completed at back-right-top, and the single-step
  `z_ceiling_camera_test.yaml` run completed successfully with one executed
  step (campaign 9). It captured
  `/home/polar/.cubos/images/campaign_9/z_ceiling_validation_20261006-191721.tiff`.
  The final gantry state was connected and Idle at
  `(35.274, 97.718, 84.058)` with no active protocol. No pipette or capper
  action occurred.
- A subsequent non-moving capper I/O check used CubOS's configured
  `NanoTextCapper` driver. The Nano accepted the `CAP_MODULE` identity probe,
  the cap sensor consistently reported no cap, `MAGNET ON` and `MAGNET OFF`
  were both acknowledged, the final cleanup sent `MAGNET OFF` again, and the
  driver health check passed. The gantry did not move and remained connected
  and Idle at `(35.274, 97.718, 84.058)` with no active protocol. A positive
  cap-present sensor check and the controlled decap/recap motion test remain.
- With the operator holding a loose cap at the pickup/sensor face, a second
  CubOS driver check reported `cap_present=true` and passed its health check.
  No magnet command or gantry movement was issued. The cap sensor has now
  passed both absent and present states; controlled decap/recap motion remains.
- Before the capper-only motion test, live `cnc.safe_z` was raised from
  `78.0` to `84.0` because the former mapped the capper to carriage Z `38.0`,
  `0.39 mm` below its calibrated contact target. The new approach maps to
  carriage Z `44.0`, about `5.6 mm` above contact. The preceding gantry config
  is backed up at
  `/home/polar/cubos-data/backups/capper-safe-z-20261006-194500/polar-bear-4040.yaml`.
  Both the two-step capper test and full eight-step protocol passed offline
  setup validation after this change.
- The operator-authorized A1 decap/recap test successfully decapped, but recap
  failed after three release-confirmation attempts: the sensor remained
  `cap_present=True` although each magnet-off command was acknowledged. CubOS
  retracted the capper to the corrected safe plane and stopped with the
  gantry connected and Idle at `(96.210, 371.895, 44.000)`. A separate
  non-moving check confirmed firmware status `CAP=DETECTED MAGNET=OFF` and
  sent another acknowledged magnet-off cleanup. The vial/cap state requires
  physical reconciliation before any further protocol motion.
- The operator confirmed the released magnet was physically off and manually
  removed the cap retained by residual attraction. Pickup height remains
  unchanged because decap succeeded. A new capper setting,
  `release_overtravel_mm`, now applies additional downward seating only to
  recap attempts. The station is provisionally configured for `0.5 mm`.
  Focused capper validation passes (`71 passed`), and both the capper-only and
  full experiment setups validate. Previous source and config are backed up at
  `/home/polar/cubos-data/backups/capper-release-overtravel-20261006-200000`.
  A repeat capper-only hardware cycle is still required before the experiment.
- The repeat capper-only cycle passed both decap and recap (`2/2` steps,
  campaign 11), confirming that `release_overtravel_mm: 0.5` clears the cap
  sensor after release.
- A subsequent full experiment reached dispense after CubOS recorded a tip
  pickup,
  first image stack, decap, 10 uL aspiration, and recap. Its `height: 0`
  dispense commanded gantry Z `6.186`; the operator stopped the motion and the
  disposable tip bent. The operator later confirmed that no disposable tip
  had actually attached; the physical pickup therefore failed even though
  CubOS's software-only tip state advanced. CubOS retained motor control and
  reported the pipette
  still held 10 uL. The operator powered down, removed the bent tip/liquid,
  inspected the station, and later released the E-stop. No attempt was made to
  resume that interrupted run.
- Live `working_volume.z_min` is now `17.904`, adding 0.5 mm above the earlier
  observed lower stop so future too-low targets fail validation. The preceding
  gantry and protocol files are backed up at
  `/home/polar/cubos-data/backups/pipette-well-clearance-20261006-201500`.
  A dry A2-tip approach at relative heights 25, 20, and 15 mm was stopped by
  the operator during the 20 mm move. The controller reset discarded the live
  stopped coordinates, but the target command was gantry Z `26.186`. The
  operator physically identified the desired dispense point as 2 mm below
  that stopped position. Because the pickup had failed, that observation did
  not include the configured 25 mm tip extension and cannot establish the
  final dispense height. The protocol currently contains the provisional
  `dispense height: 18`, uses fresh tip A3, and passes setup validation, but it
  must not run until pickup and an attached-tip clearance check pass.
- Tip-rack `pickup_z` was lowered by 2 mm, from `73.427` to `71.427`, without
  changing the 25 mm tip length or any instrument calibration. The prior deck
  file is backed up at
  `/home/polar/cubos-data/backups/tip-pickup-depth-20261006-203000/contactangle_deck.yaml`.
  The pickup-only A2 protocol passed offline setup validation. After a fresh
  service restart and successful home to `(259.514, 380.388, 84.558)`, its
  physical run completed `2/2` steps as campaign 14 and retracted to a high
  inspection position, but the operator confirmed that A2 had not attached.
  The rack `pickup_z` was lowered another 1 mm to `70.427`, with the preceding
  deck backed up at
  `/home/polar/cubos-data/backups/tip-pickup-depth-20261006-195403/contactangle_deck.yaml`.
  The revised setup passed offline validation and its A2 pickup-only run
  completed `2/2` steps as campaign 15, but A2 again did not attach. The rack
  `pickup_z` was lowered a third 1 mm increment to `69.427`, with the preceding
  deck backed up at
  `/home/polar/cubos-data/backups/tip-pickup-depth-20261006-195521/contactangle_deck.yaml`.
  That setup passed offline validation and its A2 pickup-only run completed
  `2/2` steps as campaign 16. The operator physically confirmed that A2 was
  firmly attached, establishing `pickup_z: 69.427` as the working pickup
  height. The operator then manually removed the test tip at the high
  inspection position.
- Because the earlier well-clearance observation was made with no physical
  tip attached, its carriage height could not be reused directly. A combined
  test preserved tip state in one run: it picked up A3, then approached A1 at
  target/carriage Z `66.186`, `56.186`, and `51.186`. The last height places
  the end of the measured 25 mm tip at the same physical height as the bare
  nozzle during the earlier Z `26.186` observation. Offline setup validation
  passed, and campaign 17 completed all `4/4` steps. The gantry is connected
  and Idle at `(135.931, 71.023, 51.186)`. Physical confirmation that A3 is
  attached, centered, and clear of the plate is pending before the final
  2 mm descent.
- With the protocol inactive and the controller confirmed connected and Idle
  at `(135.931, 71.023, 51.186)`, the operator authorized the final clearance
  move. CubOS lowered Z only by 2.000 mm to `49.186`; X/Y remained fixed over
  A1, the controller returned Idle, and no move error was reported. Physical
  confirmation that this is the intended dispense height is pending. If it is
  confirmed, the equivalent protocol-relative well height is `43.0` mm
  (`6.186 + 43.0 = 49.186`) for a tracked 25 mm attached tip.
- The operator reported that Z `49.186` was still too high and authorized an
  additional 10.000 mm Z-only descent. With the run inactive and controller
  state rechecked, CubOS moved to `(135.931, 71.023, 39.186)` and returned
  connected/Idle with no move error. This corresponds to protocol-relative
  `height: 33.0`; physical confirmation is pending.
- The operator requested a further 10.000 mm Z-only descent. CubOS rechecked
  the inactive run and exact starting position, moved to
  `(135.931, 71.023, 29.186)`, and again returned connected/Idle with no move
  error. This corresponds to protocol-relative `height: 23.0`; physical
  confirmation is pending before any further descent.
- The operator requested a final 2.000 mm Z-only adjustment. CubOS moved from
  Z `29.186` to `27.186` at the same A1 X/Y, returning connected/Idle with no
  move error. This corresponds to protocol-relative `height: 21.0`; the
  operator physically confirmed that the attached tip is at the intended
  bottom-of-well dispense position.
- The live full experiment now uses confirmed dispense `height: 21` and fresh
  tip A4 because A3 was consumed by clearance calibration. Aspirate remains at
  `height: 0`; a requested 10 mm deeper aspiration would use `height: -10`
  because negative labware-relative height lowers the tool. The previous
  protocol is backed up at
  `/home/polar/cubos-data/backups/confirmed-well-dispense-20261006-200408/contact_angle_a1.yaml`.
  The revised eight-step experiment passes offline setup validation. No full
  experiment was started; at that point the A3 calibration tip remained
  physically attached at the confirmed A1 position pending authorized
  retraction.
- The operator authorized disposal of the A3 calibration tip. After verifying
  the run was inactive and the gantry was connected/Idle at the exact expected
  A1 pose, CubOS retracted vertically to Z `84.0`, traveled at that clearance
  to the configured disposal, descended to Z `30.0`, and the configured Picus
  driver completed `TIP_EJECT`. The bare pipette then retracted vertically to
  `(75.89, 301.24, 84.0)`. The final controller state is connected/Idle with
  no move error. The validated full experiment remains configured to pick A4.
- The operator reported that the configured disposal action Z `30.0` was too
  low and requested an inspection point 28 mm below the high-clearance pose.
  With no tip attached, the run inactive, and the gantry connected/Idle at
  `(75.89, 301.24, 84.0)`, CubOS moved Z only to `56.0`. The controller
  returned connected/Idle with no move error. The operator confirmed this
  height, so live `tip_disposal_1.location.z` is now `56.0`. The previous deck
  is backed up at
  `/home/polar/cubos-data/backups/tip-disposal-height-20261006-201026/contactangle_deck.yaml`.
  The complete eight-step experiment passes setup validation with the revised
  disposal height.
- At the operator's request, the live experiment aspiration changed from
  labware-relative `height: 0` to `height: -10`, placing the tracked tip 10 mm
  below the calibrated vial-rim reference during its 10 uL draw. The previous
  protocol is backed up at
  `/home/polar/cubos-data/backups/aspirate-height-minus10-20261006-201330/contact_angle_a1.yaml`.
  No hardware moved, and the complete eight-step setup again passes bounds and
  semantic validation.
- Camera filenames from the successful full run used only the explicit
  `before_dispense_white` / `after_dispense_white` labels, although each image
  remained correctly attributed to `ursa_wellplate.A1` in the experiment
  database. The live protocol labels now include the target explicitly:
  `ursa_wellplate.A1_before_dispense_white` and
  `ursa_wellplate.A1_after_dispense_white`. The previous protocol is backed up
  at
  `/home/polar/cubos-data/backups/image-label-well-20261006-204159/contact_angle_a1.yaml`.
  The complete setup passes validation and no hardware moved.
- Curvature-stack filenames now report the protocol's labware-relative image
  height instead of the controller carriage Z. For `image_height: 125`, ten
  planes, and `z_step_mm: 0.2`, future filenames run from
  `height=125-000mm` through `height=123-200mm`; the calculation is
  `image_height - index * z_step_mm`. This is combined with the explicit well
  labels above. The prior live camera source and focused test are backed up at
  `/home/polar/cubos-data/backups/image-height-filenames-20261006-205000`.
  Focused camera validation passes (`30 passed`), CubOS was restarted and
  reconnected without motion at home, and the complete experiment setup
  passes validation.
- A separate live protocol is ready for the next contact-angle sample at
  `/home/polar/cubos-data/configs/protocol/contact_angle_b1_pama_water.yaml`.
  It picks a fresh tip from `tip_rack_green.A1`, images well
  `ursa_wellplate.B1` before and after dispensing with labels
  `ursa_wellplate.B1_PAMA_water_before_dispense_white` and
  `ursa_wellplate.B1_PAMA_water_after_dispense_white`, decaps and aspirates
  10 uL from `vial_rack.A1` at `height: -10`, recaps the vial, dispenses into
  B1 at the confirmed `height: 21`, and drops the tip at the confirmed
  disposal height. The original A1 protocol was preserved and backed up at
  `/home/polar/cubos-data/backups/b1-pama-water-20261006-205040/contact_angle_a1.yaml`.
  The B1 protocol passes complete setup validation and is selected in the
  CubOS UI. The gantry remains connected/Idle at home and no protocol motion
  was started. Before running, remove the manually attached pipette tip left
  from the prior inspection so the first pick-up-tip step starts with a bare
  pipette.
- The B1 PAMA-water protocol completed as campaign 19. Both ten-plane image
  stacks are present under `/home/polar/.cubos/images/campaign_19` with the
  expected B1, sample, before/after, and labware-relative height fields in
  their filenames. After the run, CubOS reported no active protocol and the
  gantry connected/Idle at the configured disposal pose
  `(75.89, 301.24, 56.0)`.
- The next live protocol is
  `/home/polar/cubos-data/configs/protocol/contact_angle_b2_pbd_water.yaml`.
  It advances to fresh tip `tip_rack_green.A2`, images and dispenses into
  `ursa_wellplate.B2`, labels the two image stacks
  `ursa_wellplate.B2_pbd_water_before_dispense_white` and
  `ursa_wellplate.B2_pbd_water_after_dispense_white`, and retains the
  confirmed 10 uL aspiration from `vial_rack.A1` at `height: -10`, dispense
  `height: 21`, white-light curvature stack, recapping, and tip disposal.
  The source B1 protocol is backed up at
  `/home/polar/cubos-data/backups/b2-pbd-water-20261006-205930/`.
  B2 is selected in CubOS and reports `Protocol is valid`; no B2 protocol
  motion was started.

Before the next homing test, clear the full travel area, keep a hand at the
gantry power switch, connect through CubOS, verify live `$23=0`, and stop
immediately if any axis moves away from back-right-top.

For deck calibration, use the pipette as the reference instrument and follow
the wizard one item at a time. Save the new deck YAML before leaving the Deck
tab; unsaved labware exists only in the browser working copy.
