# Protocol run flow — honest run state, validate semantics, cancel behavior

**Context:** `frontend/src/App.tsx`, `frontend/src/components/editor/ProtocolEditor.tsx`, `frontend/src/api/client.ts`, hooks. Backend: `zoo/routers/protocol.py`, `zoo/routers/gantry.py`. Depends on file 05 having added `GET /api/protocol/run-status` — if it doesn't exist yet, add it per 05 item 2. Tests: `cd frontend && npm run test`, `.venv/bin/python -m pytest tests/ -q`.

## 1. MAJOR — Cancel Run desyncs UI from hardware (`App.tsx:287-299,278-284`)

Cancel sends feed-hold then aborts the client fetch; the server-side run keeps executing, but `finally` sets `isRunning=false` — Run re-enables against a busy session, and the eventual `campaign_id` is discarded. Also `/protocol/cancel` can 200 with `{status:"cancel_requested", warning}` (gantry.py:600-605) and the warning is never shown.

**Fix:** don't abort the fetch. On cancel: keep `isRunning=true`, set a `cancelling` state (Run button label "Cancelling — waiting for protocol to stop", disabled), render the cancel response's `warning` when present, and only clear running state when the original `/protocol/run` promise settles (success or error).

## 2. MAJOR — running state invisible outside the Protocol tab and lost on reload (`App.tsx:476`)

**Fix:** (a) persistent sidebar banner when running: "● Protocol running…" + Cancel button wired to `handleCancelRun`, visible on every tab (insert above the view toggle in App's `left` panel ~line 336). (b) Poll `GET /api/protocol/run-status` via a small hook (e.g. `useRunStatus`, 2s interval); merge server state with client `isRunning` so a reload or second tab shows the run and disables Run.

## 3. MAJOR — Validate validates saved files, not on-screen edits (`App.tsx:452-467`)

With unsaved edits, "Protocol is valid." refers to stale disk content. **Fix:** in `onValidate`, if `unsavedConfigs.length > 0`, set `validationResult = {valid:false, errors:["Save your changes first — Validate checks the saved files."]}` and return (mirrors the run gate at `App.tsx:241-250`).

## 4. MAJOR — Validate failures silently ignored (`App.tsx:460-466`)

No `onError` on the mutate. **Fix:** `onError: (err) => setValidationResult({valid:false, errors:[String(err instanceof Error ? err.message : err)]})`.

## 5. MINOR — Run enabled during calibration warning (`App.tsx:474`)

Backend rejects with 400 only after the click. **Fix:** `canRun={gantryConnected && !gantryPosition.data?.calibration_warning}` and pass the warning text into `ProtocolEditor` to render as the disabled-Run reason.

## 6. MINOR — stale result banners (`App.tsx:55-57,164-167`)

`validationResult`/`runResult`/`runError` survive file switches and edits. **Fix:** clear all three in the `protocolFile` change effect; clear `validationResult` in `onLocalChange`/`onPositionsChange`.

## 7. MINOR — per-step error matching bugs (`ProtocolEditor.tsx:430-437`)

`startsWith("Step 1")` matches "Step 10"; backend legacy `/validate` emits 0-based indices while cards show 1-based. **Fix:** match with `^Step ${i}\b` regex and render indices 1-based (`e.replace(/^Step (\d+)/, ...)`).

## 8. MINOR — instrument→measurement-method map hardcoded in frontend (`ProtocolEditor.tsx:668-685`)

Duplicates CubOS truth; new instrument types silently fall back to `["measure"]`. **Fix:** add a thin backend endpoint (e.g. extend `/api/gantry/instrument-schemas` or add `/api/gantry/instrument-methods`) that reflects supported measurement methods per instrument type from CubOS (read CubOS to find the authoritative source — do not hardcode there either); consume it in `measurementMethodsForInstrument` with the current map as fallback while loading. Keep the router thin.

**Done when:** all items implemented with tests (cancel keeps running-state until run settles; sidebar banner visible from Deck tab; validate-with-dirty shows the save-first message; validate network error surfaces), full frontend + backend suites and lint green.
