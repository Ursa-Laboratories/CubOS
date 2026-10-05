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
- The last connected session also reported `$27: expected 10, got 1`. Re-read
  controller settings after reconnect and reconcile the controller with the
  YAML before trusting coordinates.
- Instrument offsets, capper engagement depth, the deck origin, and FLIR
  capture remain uncalibrated.

Before the next homing test, clear the full travel area, keep a hand at the
gantry power switch, connect through CubOS, verify live `$23=0`, and stop
immediately if any axis moves away from back-right-top.
