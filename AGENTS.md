# CubOS Agent Guide

CubOS controls real lab hardware: a GRBL CNC gantry plus mounted instruments. **This file is the source of truth for agent retrieval.** Prefer repo source over model memory; keep retrieval focused.

## Fast Start

1. Read this file and `CLAUDE.md`.
2. Jump to the **Subsystem Index** below for the area you are touching.
3. Read only the source/docs needed for the task unless you are changing shared interfaces, coordinate semantics, hardware motion, YAML schemas, or protocol setup.

## Hardware Safety

Any code/config change can affect real motion, instruments, samples, or controllers.

Always tell the user:
- Hardware touched or potentially affected.
- Offline validation performed.
- Required physical validation still pending.

Hardware-facing handoff order:
1. Run focused offline/unit validation for the edited behavior.
2. Stop and give the user the exact hardware test procedure before cleanup or broad test sweeps.
3. After the user confirms or asks to continue, clean up temporary files/checkpoints and run broader relevant tests.

Prefer dry-runs and validation scripts before commands that move gantries, start protocols, or actuate instruments.

## Coordinate Convention

CubOS deck frame:
- Origin: front-left-bottom (FLB)
- `+X`: operator-right
- `+Y`: back/away
- `+Z`: up; `-Z`: down

Do not pre-flip signs in high-level code. GRBL `$3` axis direction and `$23` homing direction must make controller WPos match this frame. `$H` homes to back-right-top (BRT). High-level gantry code applies no hidden Z sign flip; working-volume bounds are deck-frame values.

Retrieval rule: do not infer sign flips from older code or model memory. Confirm convention in source and tests.

### Heights: absolute vs. labware-relative

Two kinds of Z fields coexist:
- **Absolute deck-frame Z** (`gantry.cnc.safe_z`, working-volume bounds, `move`'s `travel_z`, named positions, literal `[x, y, z]` targets). `safe_z` is the travel ceiling: every resolved approach/action Z must be ≤ `safe_z`. Defaults to `working_volume.z_max` when omitted.
- **Labware-relative offsets** (`measurement_height`, `safe_approach_height` on `scan`/`measure`). Positive = above the labware's `height_mm` surface; negative = below. Resolved at command time as `well.z + relative_offset`.

These offsets live on the protocol command, never on instruments. `scan` requires both `measurement_height` and `safe_approach_height`; `measure` requires `measurement_height`. Pipette commands engage at the labware reference Z (`measurement_height = 0` implicitly). ASMI `indentation_limit` is a sign-agnostic descent magnitude.

## Subsystem Index

### Gantry / motion / coordinates / homing
Read before changing motion, coordinates, bounds, homing, or scan/protocol movement.
- `src/gantry/gantry.py`, `gantry_config.py`, `origin.py` — frame, working volume, deck-origin calibration.
- `src/gantry/machine_geometry.py` — built-in fixed-structure AABBs per gantry family (e.g. `cub_xl` right-rail guard). Not user-authored YAML; consumed by setup validation.
- `src/gantry/coordinate_translator.py`, `loader.py`, `yaml_schema.py`, `grbl_settings.py`, `offline.py`.
- `src/board/board.py`, `src/board/loader.py` — instrument offsets and labware movement.
- `src/validation/bounds.py`, `src/validation/protocol_semantics.py` — offline safety checks (incl. fixed-structure rail collision).
- Tests: `tests/protocol_engine/test_deck_origin_configs.py`.

Gantry YAML requires top-level `gantry_type` (`cub` or `cub_xl`). For `cub_xl`, setup validation rejects protocols whose instrument point or known travel segment would hit the fixed right X-max rail.

### Deck YAML / labware / calibration
- `src/deck/yaml_schema.py` — strict Pydantic schema.
- `src/deck/loader.py` — load-name expansion, calibration, derived wells, nested labware.
- `src/deck/labware/`, `src/deck/labware/definitions/`.
- `configs/deck/`.
- Tests: `tests/test_deck_loader.py`, `tests/test_holder_labware.py`, `tests/test_panda_deck_yaml.py`.

After schema/config changes: focused tests, then `setup/validate_setup.py` for affected real triples.

### Protocol engine / setup validation
- `src/protocol_engine/yaml_schema.py`, `loader.py`, `setup.py`.
- `src/protocol_engine/commands/` — command behavior.
- `setup/validate_setup.py` — end-to-end offline validation.
- `configs/protocol/`.
- Tests: `tests/protocol_engine/`.

```bash
python setup/validate_setup.py <gantry.yaml> <deck.yaml> <protocol.yaml>
```

### Instruments
- `src/instruments/<instrument>/driver.py`, `mock.py`, `models.py`, `exceptions.py`.
- `src/instruments/registry.yaml`, `src/instruments/yaml_schema.py`.
- `src/protocol_engine/measurements.py`, `data/data_store.py` — persisted measurements.
- Tests: `tests/instruments/`, `tests/protocol_engine/`, `tests/data/`.

## Calibration Scripts

- `setup/calibrate_gantry.py` — only supported user-facing calibration entrypoint. Loads input gantry YAML, dispatches single- or multi-instrument flow by instrument count. Without `--output-gantry`, prompts before overwriting input; with it, writes the explicit path without extra prompt.
- `setup/calibration/single_instrument_calibration.py` — internal one-instrument flow.
- `setup/calibration/multi_instrument_calibration.py` — internal multi-instrument flow.
- Detailed operator steps and offset math live in `docs/calibration.md`.

## Setup Scripts

- `setup/validate_setup.py` — offline gantry+deck+protocol bounds/semantics validation. PASS/FAIL.
- `setup/run_protocol.py` — load, validate, connect hardware, run protocol end-to-end. Connects gantry (clearing expected GRBL alarm, restoring state) and instruments before first step; disconnects in `finally`.
- `setup/hello_world.py` — interactive deck-origin jog test. Homes without rewriting WCS, then jogs in the deck frame. Arrow keys (X/Y ±1mm), Z (down 1mm), X (up 1mm), Q (quit).
- `setup/keyboard_input.py` — single-keypress reader (Unix `tty`/`termios`).

## Debugging Mode

If the user is actively debugging, prioritize fast diagnosis over the TDD loop. Do not add or run unit tests during the debugging cycle unless asked or until the bug is fixed. Temporary instrumentation is OK if tagged and removed before finalizing.

## Progress Notes

See `progress/README.md`. Default: no progress file. Create only for hardware-facing motion changes, refactors >5 files, or explicit handoffs. Delete on PR merge.

## Verification Gates

Smallest meaningful gate first, then broaden:

```bash
python -m pytest tests/test_deck_loader.py tests/test_holder_labware.py -q
python -m pytest tests/protocol_engine -q
python -m pytest -q
python setup/validate_setup.py configs/gantry/cub_xl_asmi.yaml configs/deck/asmi_deck.yaml configs/protocol/asmi_indentation.yaml
```

Report exact commands and observed results in the PR body.

## When to Update This File

Update `AGENTS.md` only when agent retrieval, hardware-safety workflow, or source-of-truth pointers change. Update `README.md` / docs only when public CLI/workflow, YAML schema/config, coordinate/motion/calibration semantics, protocol behavior, or cross-repo interfaces change.
