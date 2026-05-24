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

`scan.plate` may target either a top-level `WellPlate` key or a nested holder path such as `plate_holder.plate`, as long as that path resolves to a `WellPlate`.

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
