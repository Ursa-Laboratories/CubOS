# CubOS Agent Guide

CubOS controls real lab hardware: a GRBL CNC gantry plus mounted instruments.
Prefer repo source over model memory; keep retrieval focused.

## Fast Start

1. Read this file and `CLAUDE.md`.
2. Use `docs/agent-index.md` to find the source/docs for the area you are touching.
3. Read only the files needed for the task unless you are changing shared interfaces, coordinate semantics, hardware motion, YAML schemas, or protocol setup.

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
- **Absolute deck-frame Z** (`gantry.cnc.safe_z`, working-volume bounds, `move`'s `travel_z`, named positions, literal `[x, y, z]` targets). `safe_z` is the travel ceiling: every resolved approach/action Z must be <= `safe_z`. Defaults to `working_volume.z_max` when omitted.
- **Labware-relative offsets** (`measurement_height`, `interwell_scan_height`, `indentation_limit_height` on `scan`/`measure`). Positive = above the well's calibrated surface Z; negative = below. Resolved at command time as `well.z + relative_offset`, where `well.z` is the calibration anchor's z. The labware's `height` is the physical outer dimension, not a Z reference.

These offsets live on the protocol command, never on instruments. `scan` requires both `measurement_height` and `interwell_scan_height`; `measure` requires `measurement_height`. Pipette commands engage at the labware reference Z (`measurement_height = 0` implicitly). ASMI `indentation_limit_height` is a signed labware-relative offset (negative = below the well surface); must be at or below `measurement_height`.

## Active Retrieval

`docs/agent-index.md` is the detailed retrieval map for gantry, deck, protocol, instrument, calibration, setup, exception-handling, and testing work. Keep long source lists there, not here.

For setup validation:

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

Calibration soft-limit rule: `working_volume` is the usable deck/WPos range
after homing pull-off. GRBL `$130/$131/$132` and YAML
`grbl_settings.max_travel_*` are controller spans and must include the `$27`
homing pull-off reserve. Calibration sets `$10=0` for WPos status reporting,
writes the per-machine `grbl_settings.homing_pull_off` (`$27`) before homing
when configured, and saves/programs max travel as usable span plus pull-off.
Do not treat the pull-off reserve as usable WPos.

## Setup Scripts

- `setup/validate_setup.py` — offline gantry+deck+protocol bounds/semantics validation. PASS/FAIL.
- `setup/run_protocol.py` — load, validate, connect hardware, run protocol end-to-end. Connects gantry (clearing expected GRBL alarm, restoring state) and instruments before first step; disconnects in `finally`.
- `setup/hello_world.py` — interactive deck-origin jog test. Homes without rewriting WCS, then jogs in the deck frame. Arrow keys (X/Y ±1mm), Z (down 1mm), X (up 1mm), Q (quit).
- `setup/keyboard_input.py` — single-keypress reader (Unix `tty`/`termios`).
`scan.plate` may target either a top-level `WellPlate` key or a nested holder path such as `plate_holder.plate`, as long as that path resolves to a `WellPlate`.

## Hardware Iteration Mode

Covers two situations where TDD is deferred:

- **Debugging**: fast diagnosis of an existing bug — skip tests until the fix is confirmed, then add a regression test.
- **Iterative hardware testing**: small changes (calibration, GRBL params, YAML tweaks, motion adjustments) where physical validation must come before tests are meaningful.

In both cases: make the minimal targeted change, mark deferred work `# TODO(iter): test` or `# TODO(iter): doc`, and sweep those tags at close-out. Temporary instrumentation is OK if tagged and removed before finalizing.

See root `AGENTS.md` for the full Development Modes definition.

## Progress Notes

See `progress/README.md`. Default: no progress file. Create only for hardware-facing motion changes, refactors >5 files, or explicit handoffs. Delete on PR merge.

## Verification Gates

Smallest meaningful gate first, then broaden:

```bash
python -m pytest tests/test_deck_loader.py tests/test_holder_labware.py -q
python -m pytest tests/protocol_engine -q
python -m pytest -q
python setup/validate_setup.py configs/gantry/cub_xl_asmi.yaml configs/deck/asmi_deck.yaml configs/protocol/asmi/indentation.yaml
```

Report exact commands and observed results in the PR body.

## When to Update This File

Update `AGENTS.md` only when agent retrieval, hardware-safety workflow, or source-of-truth pointers change. Update `README.md` / docs only when public CLI/workflow, YAML schema/config, coordinate/motion/calibration semantics, protocol behavior, or cross-repo interfaces change.
