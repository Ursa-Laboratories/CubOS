# Zoo UI/UX Cleanup

Status: complete

## Goal
- Improve config selection, protocol step creation, calibration/deck coordinate labels, and gantry recovery controls.

## Findings
- Existing gantry routes already exposed CubOS-backed unlock and settings validation; new recovery controls could stay thin by adding endpoints over CubOS `Gantry` methods.
- Browser validation showed definition-backed deck YAMLs could display literal `undefined` in numeric fields, so shared numeric inputs now render missing values as empty fields.
- Follow-up visual validation caught stretched config controls and `NaN` SVG coordinates from legacy deck keys (`x_offset`/`y_offset`). The deck API now exposes editor-friendly fields on read and coerces them back to CubOS YAML keys on preview/save.
- The protocol add-step control moved below the protocol body, with an empty state for the no-steps case.

## Files
- `frontend/src/components/editor/ImportFromFile.tsx`
- `frontend/src/components/editor/ProtocolEditor.tsx`
- `frontend/src/components/editor/fields.tsx`
- `frontend/src/components/deck/DeckVisualization.tsx`
- `frontend/src/components/gantry/GantryPositionWidget.tsx`
- `zoo/routers/deck.py`
- `zoo/routers/gantry.py`
- `README.md`
- `docs/repo-overview.md`

## Verification
- `npm run lint`
- `npm run test`
- `npm run build`
- `PYTHONPATH=../CubOS/src:. .venv/bin/pytest tests -q`
- Playwright visual pass against `http://127.0.0.1:8742`
