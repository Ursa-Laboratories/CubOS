# Calibration wizard safety — refresh recovery, retry idempotency, frame integrity

**Context:** `frontend/src/components/gantry/CalibrationWizard.tsx` + small backend additions in `zoo/routers/gantry.py` / `zoo/models/gantry.py`. CubOS session semantics at `/Users/alexchan/Documents/Ursa/CubOS/src/gantry/session.py` (read-only). Tests: `cd frontend && npm run test` (see `CalibrationWizard*.test.tsx` for harness patterns) and `.venv/bin/python -m pytest tests/ -q`.

## 1. CRITICAL — browser refresh mid-calibration leaves soft limits disabled with no indication

After `prepare-origin`, GRBL soft limits are disabled and jogs bypass the working-volume guard (session.py:425-438, 784-789). The wizard's only cleanup is its close handler; on refresh/tab-close the backend session survives, and the reloaded UI shows a green "Connected" badge with fully enabled jogs and no warning.

**Fix (both halves):**
- **Backend:** add `calibration_active: bool` to the position payload — in `zoo/routers/gantry.py`'s position snapshot mapping and `zoo/models/gantry.py` (+ `frontend/src/types/index.ts`). Derive from the session's calibration state (`_calibration_jog_bypass_working_volume or _calibration_restore_soft_limits` — if no public accessor exists, read the private attrs with a `getattr(..., False)` and a comment; do NOT modify CubOS).
- **Frontend:** in `CalibrationWizard.tsx`, register `beforeunload` (preventDefault + returnValue) while `open && step >= 2`. In `GantryPositionWidget.tsx`, when `position.calibration_active` is true and the wizard is closed, render a red banner "Calibration interrupted — soft limits are disabled" with a "Restore soft limits" button calling `gantryApi.restoreCalibrationSoftLimits()`.

## 2. MAJOR — retrying a failed "Set origin"/"Set Z reference" mixes coordinate frames (`CalibrationWizard.tsx:372-425`)

Both handlers capture `blockTouch = getPosition()` then `setWorkCoordinates(...)` (re-zeroing WPos). If a later await in the handler fails (restore-soft-limits, or the Z-retract `jogBlocking`), retry re-captures `blockTouch` in the already-shifted frame while `calibrationHome`/`xyBounds` stay in the old frame — plausible-but-wrong values pass validation and get written to YAML and GRBL soft limits.

**Fix:** store the first successful capture + zeroing result in a ref before the failable tail call; on retry, if the ref is set, skip re-capture/re-zero and only re-run the failed tail (restore or retract). Clear the ref when the step is left or the wizard resets. Add a vitest: fail the retract once, retry, assert `setWorkCoordinates` was called exactly once and saved values use the first capture.

## 3. MAJOR — saving calibration to a different filename leaves live guards on stale working volume

Wizard's Output YAML field is freely editable; `App.tsx:516-521` PUTs and `setGantryFile(saved.filename)`, but CubOS `refresh_connected_config` no-ops when the filename differs from the connected one (session.py:209-218). Controller soft limits are new; session jog/move guards still enforce the old file's working_volume until reconnect.

**Fix:** in `App.tsx`'s `onSaveCalibrated`, if the saved filename ≠ the currently connected filename, call `gantryApi.connect(saved.filename)` after the PUT (await it; surface errors inline). Keep the filename field editable.

## 4. MAJOR — poll-detected alarm during blocking ops can auto-jog with a stale delta (`CalibrationWizard.tsx:197-211`)

The auto-recovery effect doesn't check `busy`, and `lastJogDelta` persists from earlier manual jogs. An alarm surfaced by the 200ms poll during home/home-and-center/save re-home triggers `recoverCalibrationLimit` jogging opposite an unrelated delta, auto-unlocking without operator input.

**Fix:** add `busy` to the effect guard, and set `lastJogDelta.current = null` at the start of every blocking non-jog action (home, home-and-center, finalize/save) so poll-detected alarms fall through to the safe "no recent jog direction — use E-stop" prompt. Extend `CalibrationWizardAlarm.test.tsx` with this scenario.

## 5. Minor wizard fixes

- **Alarm re-mask window:** `resolvedAlarmStatus` (`:91,156-160`) treats an identical re-alarm as resolved until a non-alarm poll lands. Also clear `resolvedAlarmStatus` on a ~1s timer.
- **Dead branch:** the `!isMulti` branch of `setXY` (`:332-356`) is unreachable (button rendered only when `isMulti`). Delete it.
- **State wipe on prop identity change:** the reset effect (`:115-140`) wipes all captured positions if the gantry config refetches mid-flow. Reset only on the rising edge of `open` (track `prevOpen` in a ref).
- **Reset only on step 0:** show the "Reset wizard" button on all steps (disabled while `busy`), routing through the same soft-limit restore as close.

**Done when:** all items implemented, new/updated vitest cases pass, full frontend + backend suites green, `npm run lint` clean.
