# GRBL polling extraction — 2026-10-27

## Scope

Extract the status-polling behavior from PR #351 onto main `3865235b`.
Request status before reading, use an immediate first regular query followed
by a 5 Hz maximum regular cadence, and require a controller Idle report for
command completion. Keep bounded noise/silence handling and visible alarms,
errors and disconnections.

Movement paths, controller settings, feed rates and serial timeouts are unchanged.
Collision-aware routing remains in PR #371. General diagonal movement and
Color Twin changes from #351 are excluded. Neither older PR is closed by
this extraction.

## Offline verification

Tests use this worktree's own editable CubOS installation and Python environment.
All serial devices are fakes; no station, controller, instrument or live
configuration is accessed.

- Fifteen new serial/clock regressions pass. Against main's driver loaded in
  memory, twelve of these checks fail and three unchanged behaviors pass.
- `.venv/bin/python -m pytest packages/core/tests/gantry/driver/test_status_polling.py packages/core/tests/gantry/driver/test_gantry_driver.py packages/core/tests/gantry/driver/test_wpos_enforcement.py -q --cov=packages/core/src/cubos --cov-report=xml`
  — 86 passed, 8 subtests passed.
- `.venv/bin/python -m pytest packages/core/tests --cov=packages/core/src/cubos --cov-report=xml -q`
  — 2,642 passed, 20 skipped, 14 subtests passed.
- `.venv/bin/diff-cover coverage.xml --compare-branch=origin/main --fail-under=90`
  — 100% changed-core coverage (21/21 lines).
- `.venv/bin/python -m mkdocs build --strict` — passed.
- `.venv/bin/python -m cubos.tools.validate_setup packages/core/configs/gantry/cub_xl_asmi.yaml packages/core/configs/deck/asmi_deck.yaml packages/core/configs/protocol/asmi/indentation.yaml`
  — passed, 195 targets, offline only.
- Independent diff review found no material introduced defect; movement command
  construction is unchanged. Hosted CI will validate the PR against main.

## Operator validation required before merge

Potentially affected hardware: GRBL-controlled gantries whose command
completion is observed by CubOS. Physical timing and hold behavior have not
been validated for this extraction. No deployment has been performed.

With an operator present, an empty calibrated machine, its known-good
configuration, a verified clear interior pose, and the physical stop accessible:

1. Validate that machine's gantry/deck/protocol files with
   `python -m cubos.tools.validate_setup <gantry.yaml> <deck.yaml> <protocol.yaml>`.
2. Through CubOS, perform a single clear 1 mm move and return to the recorded
   reference position. Compare command/completion timestamps against the prior
   version; confirm the displayed and observed final position. Do not change
   speed, calibration or controller settings to obtain a favorable result.
3. Supervise a short, clear, low-speed move. Use Operator feed hold and verify
   that the controller reports Hold and the move is not reported complete.
   Resume only after inspecting the machine and explicitly choosing to resume.
4. Confirm the original axis-by-axis travel path is preserved. No diagonal
   routing or liquid-handling test is needed for this polling-only change.

Error/alarm/disconnection and malformed-message tests are offline fault
injection only. Do not deliberately trip limits, disconnect a moving controller,
or replay an interrupted experiment. Offline results do not establish physical
motion safety or a measured speedup.
