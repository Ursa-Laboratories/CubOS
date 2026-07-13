# CubOS Server and Web Agent Guide

The imported Zoo server and web UI remain a thin layer over CubOS.


## Retrieval-Led Agent Index

Before coding, prefer repo source/docs over model memory. Use `docs/agent-index.md` as the compact routing map for where to look before touching backend routes, CubOS integration, frontend config editors, coordinate display, tests, or docs.

Key rule: Zoo stays a thin layer over CubOS. Read the relevant source/docs from the index instead of relying on optional skill invocation or remembered semantics.

## Core Rules

- Do not duplicate CubOS validation, protocol, or hardware logic here.
- Routers should stay thin and rely on CubOS loaders, schemas, registries, and runtime classes.
- Frontend types should model API payloads, not become a second source of truth for CubOS semantics.
- Keep hardware-touching behavior explicit. Gantry routes can home, jog, move, unlock, and run protocols.

## Key Paths

- `zoo/app.py`
- `zoo/__main__.py`
- `zoo/config.py`
- `zoo/routers/`
- `zoo/services/`
- `../web/src/api/`
- `../web/src/components/`
- `../web/src/hooks/`
- `tests/`

## Runtime Model

1. Frontend collects config edits.
2. Zoo writes YAML to the active config directory.
3. Zoo reads the same files back through CubOS loaders or schemas.
4. Derived results are returned to the UI.

## Commands

```bash
pytest tests/
cd ../web && npm run lint
cd ../web && npm run test
cd ../web && npm run build
python -m zoo
```

## Coordinate Convention

Zoo follows CubOS' deck-origin frame directly: front-left-bottom origin, +X right, +Y back, +Z up. Do not negate X/Y in the frontend. Jog controls send CubOS-relative deltas as-is: left=-X, right=+X, up=+Y, down=-Y, X=+Z, Z=-Z.

## Gantry Calibration Semantics

Zoo must preserve CubOS' split between usable deck coordinates and GRBL controller travel:

- `working_volume` is the user-visible deck/WPos usable range after the machine has homed and pulled off the switches.
- `grbl_settings.max_travel_x/y/z` mirrors GRBL `$130/$131/$132` and is the controller soft-limit span, so it includes the `$27` homing pull-off reserve.
- Calibration sets `$10=0` so status reports are WPos, not MPos, before capturing homed positions.
- Calibration writes the configured per-machine `grbl_settings.homing_pull_off` (`$27`) before calibration homing. Single-instrument finalization can also read the live `$27` and save it back.
- Example: if homed WPos Z is `91` and `$27=10`, save `working_volume.z_max=91` but program/save `grbl_settings.max_travel_z=101`.

Do not assign the pull-off reserve as usable WPos. Normal gantry jogs are guarded against `working_volume`; calibration jogs bypass that guard only while the wizard has intentionally disabled soft limits.

## Local State

- Default config directory: `configs/`
- Settings are exposed through `/api/settings`
- Frontend build output lives in `../web/dist/`

## Documentation Contract

Keep these files updated when behavior changes:

- `README.md`
- `docs/repo-overview.md`
- `../docs/*` for cross-repo effects
