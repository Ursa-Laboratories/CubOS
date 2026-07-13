# Gantry widget — keyboard jog scoping, run-state lockout, error surfacing

**Context:** `frontend/src/components/gantry/GantryPositionWidget.tsx` + `frontend/src/App.tsx`. Tests: `cd frontend && npm run test`. Coordinate convention (AGENTS.md): left=-X right=+X up=+Y down=-Y X-key=+Z Z-key=-Z — do not change it.

## 1. CRITICAL — global keyboard jog handler is unscoped (`GantryPositionWidget.tsx:104-141`)

Four confirmed leaks: (a) fires while the calibration wizard modal is open, bypassing wizard busy/alarm locks and its limit-recovery bookkeeping; (b) fires during protocol runs (App disables polling at `App.tsx:95`, so `connected` is frozen true) — jogs queue on the session lock and execute as surprise motion when the run ends; (c) guard excludes only `INPUT`, so arrow keys inside `<select>` dropdowns jog the machine; (d) `keyup` never arrives on alt-tab/window blur, so the 150ms interval jogs forever.

**Fix:** in the keydown effect: bail when the calibration wizard is open (pass `calibrationOpen` into the guard), when a run is active (see item 2), and when `e.target` is INPUT/SELECT/TEXTAREA/BUTTON or `isContentEditable`; add `window` `blur` + `document` `visibilitychange` listeners that call `stopJog()`. Tests: keydown with a `<select>` focused → no jog fetch; `blur` while held → interval cleared.

## 2. MAJOR — manual controls stay live during a protocol run; readout freezes (`App.tsx:95,511-523`, widget `:270`)

During a run the position poll is disabled (stale readout, frozen badge) while Jog/Home/Move To/Advanced remain clickable — commands queue on the session lock and fire post-run.

**Fix:** keep polling during runs (CubOS `position()` is a lock-free cached snapshot — session.py:220-240 — so `useGantryPosition(true)` is safe; remove the `!isRunning` gate) and pass `isRunning` into `GantryPositionWidget`; fold it into `jogDisabled`, Home/Move To/Advanced disabled states, and the keyboard guard; show a "Protocol running — manual control locked" note in the widget. (If backend file 05 added `GET /api/protocol/run-status`, prefer server state via a small polling hook in `frontend/src/hooks/` so a second tab/reload also locks controls.)

## 3. MAJOR — command errors invisible (`move_error` never rendered; jog/home/unlock → console.error)

`position.move_error` (populated by CubOS background move worker, returned on every poll) has zero frontend references; jog rejections (working-volume 400), failed Home, failed unlock all sink to `console.error` (`:71,172,225`).

**Fix:** add a `lastCommandError` state rendered as a dismissible inline red strip in the widget (near the controls); set it in the jog/home/unlock/move catch blocks and from `position.move_error`; clear on next successful command. Test: jog route returns 400 → strip renders the message.

## 4. MAJOR — no jog-cancel on release; queued jogs continue after mouseup (`:75-90`, wizard `:142-147`)

Hold-to-jog issues a jog per 150ms; with step >~5mm the GRBL planner queues seconds of motion that continue after release. `gantryApi.jogCancel()` exists but is only in the Advanced panel.

**Fix:** in both `stopJog` implementations (widget + `CalibrationWizard.tsx`), after clearing the interval, call `gantryApi.jogCancel().catch(() => {})` — only when more than one interval tick was sent (track tick count) so single taps don't spam cancel.

## 5. MAJOR — wizard modal lacks a focus trap (`CalibrationWizard.tsx:583`)

Tab reaches background Disconnect/Home buttons under the overlay; Enter activates them invisibly mid-calibration. **Fix:** while open, apply `inert` to the backgrounded app content (or a minimal focus trap: focus dialog on open, cycle Tab within, restore on close, Escape → same path as the × button, blocked while `busy`).

## 6. Minor

- **Step "0" jogs 0.5mm:** `parseFloat(step) || 0.5` (`:266-267`, wizard `:577-578`). Replace with explicit `Number.isFinite(v) && v > 0` gate; invalid/empty disables jog buttons with an inline hint.
- **Silent client-side jog guard:** when the predictive guard blocks (`:55-73`), show a transient "At working-volume limit" hint; don't reset the prediction backwards from stale polls while `jogTimer` is active.

## 7. UX polish (all small)

- "Calibrate now" button inside the CALIBRATION NEEDED banner (`:341-357`) → opens the wizard.
- Move To: label inputs "X (mm)" etc., placeholders showing working-volume range, replace both `alert()` validations with an inline red hint.
- Step-size preset chips (0.1 / 1 / 10 mm) beside XY/Z step inputs in widget and wizard.
- Home button shows "Homing…" while its operation is in flight.
- After wizard save, show a success line in the widget: "Saved <file> — X 0–<xmax>, Y 0–<ymax>, Z 0–<zmax> mm".

**Done when:** all items implemented, new tests for items 1–3 pass, full frontend suite + lint green.
