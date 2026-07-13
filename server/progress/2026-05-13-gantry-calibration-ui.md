# Gantry Calibration UI

Status: complete

## Goal
- Add a Zoo calibration UI for the CubOS `setup/calibrate_gantry.py` workflow.

## Findings
- CubOS branches calibration by gantry instrument count: single-instrument deck-origin calibration and multi-instrument board calibration.
- The canonical CubOS flow is serial: prepare the controller, disable stale soft limits only for XY origining, set the work coordinates, re-home/capture bounds/move center for multi-instrument boards, retract Z after each shared-block measurement, then re-home for final volume and soft-limit programming.
- Current CubOS gantry YAML schema uses `gantry_type` and `cnc.factory_z_travel_mm`; Zoo's gantry editor and compatibility loader needed to handle that shape.
- Zoo can stay a thin layer by exposing work-coordinate and soft-limit routes that delegate to CubOS `Gantry` methods.
- The calibration wizard now follows that sequence without clickable step backtracking; automatic home/center/retract operations block the UI while the gantry is moving.
- The broader backend suite had one stale deck fixture using retired CubOS field names; it was updated to the current schema so the full validation pass remains useful.
- Zoo's deck geometry serializer also needed to accept CubOS' current `length`/`width`/`height` geometry attributes while preserving the existing API response names.

## Files
- `zoo/routers/gantry.py`
- `zoo/routers/deck.py`
- `frontend/src/components/gantry/CalibrationWizard.tsx`
- `frontend/src/components/gantry/GantryPositionWidget.tsx`
- `frontend/src/components/editor/GantryEditor.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/types/index.ts`
- `tests/test_gantry_router.py`
- `tests/test_deck_router.py`
- `frontend/src/App.test.tsx`
- `README.md`
- `docs/repo-overview.md`
- `docs/agent-index.md`

## Verification
- `pytest tests/test_gantry_router.py -q`
- `pytest tests -q`
- `cd frontend && npm run lint`
- `cd frontend && npm run test`
- `cd frontend && npm run build`
- Live smoke on `http://127.0.0.1:8743`: `/api/settings`, `/api/deck/sterling_deck.yaml`, `/api/gantry/configs`, and `/` all returned successfully after server restart.
- `git diff --check`

## Next Steps
- Run calibration only with the gantry path clear, the calibration block ready, and the E-stop reachable.
