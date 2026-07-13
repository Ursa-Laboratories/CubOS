# Frontend test gaps — hardware widget, run failures, payload assertions

**Context:** Zoo frontend (React+TS+Vitest, `frontend/`) is at 81.5% statements with 112 passing tests. Tests stub `global.fetch` with route tables (see `CalibrationWizardAlarm.test.tsx` and the stateful mock in `src/App.test.tsx` for patterns to copy — no MSW, no snapshots). Run with `cd frontend && npm run test`.

**Goal:** add/tighten the following tests. Do not change production code except the one dead-code deletion in item 6.

## 1. `GantryPositionWidget` — worst-covered component (63.5%) and it drives hardware

In `frontend/src/components/gantry/GantryPositionWidget.test.tsx`:
- `POST /api/gantry/connect` returns 500 → assert `Connection failed` text renders and the button returns to "Connect".
- Open Advanced panel, click Read GRBL Settings with response `{settings: {"$20":"1","$3":"5"}}` → assert rows render with `$3` sorted before `$20`.
- Type setting `$20` value `1`, click Send Setting → assert fetch hit `/api/gantry/grbl-settings` with body `{"setting":"$20","value":"1"}`.
- Render with `position={status:"ALARM:1"}` → assert ALARM banner shows and Unlock POSTs `/api/gantry/unlock`.
- Tighten the existing test near line 61 ("sends the move"): assert the URL is `/api/gantry/move-to` with body `{x:999,y:999,z:999}` instead of just "fetch was called".

## 2. `App.test.tsx` — run-failure and validate-guard paths

- Override `POST /api/protocol/run` in `installFetchMock` to return `new Response("Gantry lost connection", {status: 500})`; after connect + Run, assert the error text renders (match whatever format `api/client.ts` produces at implementation time — prompt file 11 item 7 changes it to parse `detail` and drop the raw JSON) and the Run button re-enables (not stuck on "Running…"/"Cancelling…").
- Click Validate with no protocol file selected → assert "Select gantry, deck, and protocol files before setup validation." renders (`App.tsx:454-458`).
- `validate-setup` returning `{valid:false, errors:["step 2: unknown position"]}` → assert the error renders (first exercise of `ProtocolEditor`'s `validationErrors` prop).

## 3. New `frontend/src/components/data/DataOutputPanel.test.tsx` (direct props, no App harness)

- `error={new Error("db locked")}` → assert `Data load failed: db locked`.
- `campaigns=[]` → "No campaigns found.".
- Campaign with `measurement_count: 0` → Export button disabled.
- Stub fetch so export endpoint returns 500 → click Export → assert `Export failed` renders and the button re-enables (`exportingId` reset).

## 4. `ProtocolEditor.test.tsx` — payload assertions instead of call counts

- In "adds, reorders, and removes steps": replace `toHaveBeenCalledTimes(3)` with `toHaveBeenNthCalledWith(2, [scanStep, moveStep])` (reorder) and `toHaveBeenNthCalledWith(3, [moveStep])` (removal).
- In the position-rename test: assert `onLocalChange` last payload contains `args: expect.objectContaining({position: "park2"})` and `onPositionsChange` last call is `{park2: [1,2,3]}`.

## 5. `GantryEditor.test.tsx` — instrument type-change remap (bug here writes invalid YAML)

Using the existing stateful harness: change an `asmi` instrument's Type select to `pipette`; assert `onLocalChange` last payload has `type:"pipette"`, a vendor valid for pipette (remapped away from `vernier`), schema-default fields populated, and stale ASMI-only fields dropped. Covers `GantryEditor.tsx:334-346`.

## 6. New `frontend/src/api/client.test.ts` + dead-code removal

- **Delete `rawApi` from `frontend/src/api/client.ts` (lines ~247-255)** — zero callers in `src/`.
- Stub fetch; assert `request()` throws `Error` with message format `"404: <body text>"` on non-ok (this exact format is load-bearing for every error banner in the app), sends `Content-Type: application/json`, and `download()` throws on non-ok / resolves a Blob on ok.

**Done when:** `npm run test` passes with all new tests, `npm run lint` is clean, and `npx vitest run --coverage` shows `GantryPositionWidget.tsx` ≥ 85% statements and overall statements ≥ 88%.
