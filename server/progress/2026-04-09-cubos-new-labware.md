# CubOS staging deck compatibility

Status: complete

## Goal
- Point Zoo's `cubos` dependency at the `staging` branch.
- Make Zoo load and visualize the staging-format `panda_deck.yaml`.
- Support `tip_rack`, `well_plate_holder`, and `vial_holder` entries in Zoo's deck API and frontend.

## Findings
- The deck visualization was still drawing Y in SVG-native top-down order, so the left axis showed `0` at the top while X started from the bottom-left origin.
- Reproduced the reported bug against the real CubOS config directory: importing `panda_deck.yaml` initially failed because Zoo was importing an older installed `deck` package that did not support `load_name`.
- The current frontend also assumes every imported deck item has editor-friendly `name`, `model_name`, and `type` fields; CubOS-native tip racks and holders violate that assumption, so the deck UI needs to treat those entries as loadable-but-not-fully-editable instead of assuming flat well-plate/vial shapes.
- `cubos` was pinned to `new-labware` in `pyproject.toml` and `requirements.txt`; both now point to `staging`.
- `configs/deck/panda_deck.yaml` is a new file on the CubOS branch relative to `main`.
- The Panda deck defines:
- two `tip_rack` entries (`tip_rack_a`, `tip_rack_b`) with 2x15 tips each,
- one `well_plate_holder` containing a nested `well_plate`,
- one `vial_holder` containing nine nested `20ml_vial` entries.
- Holder-contained labware omits child `z`; CubOS derives child Z from the holder seat height.
- A forced reinstall of `cubos @ git+file:///Users/alexchan/Documents/hephaestus/CubOS@staging` updated the installed `deck` loader to the staging version.
- The staging `cubos` package still omitted `deck/labware/definitions/registry.yaml` and the bundled definition folders from site-packages, so `load_name` resolution still failed until those assets were copied into the installed package.
- Zoo's deck router now returns CubOS-resolved `location`, `geometry`, and `positions` metadata for every deck item, which the frontend uses to render tip racks and holder-contained labware without reproducing CubOS coordinate math in TypeScript.
- The frontend deck visualization now renders:
- `tip_rack` footprints and tip positions,
- `well_plate_holder` envelopes plus nested well-plate wells,
- `vial_holder` envelopes plus nested vial positions.
- The deck editor still only offers detailed form editing for flat `well_plate` and `vial` entries; holder and tip-rack configs load safely and are preserved on save, but show a note that detailed editing is not implemented yet.
- CubOS changed the private `_derive_wells_from_calibration` helper signature on `staging`, so Zoo's `/api/deck/preview-wells` route was updated to resolve Z explicitly before calling it.

## Files
- `pyproject.toml`
- `requirements.txt`
- `README.md`
- `zoo/routers/deck.py`
- `tests/test_deck_router.py`
- `frontend/src/types/index.ts`
- `frontend/src/components/deck/DeckVisualization.tsx`
- `frontend/src/utils/coordinates.ts`
- `frontend/src/utils/coordinates.test.ts`
- `frontend/src/components/deck/WellPlateRenderer.tsx`
- `frontend/src/components/deck/VialRenderer.tsx`
- `frontend/src/components/deck/TipRackRenderer.tsx`
- `frontend/src/components/deck/HolderRenderer.tsx`
- `frontend/src/components/deck/renderUtils.ts`
- `frontend/src/components/deck/DeckVisualization.test.tsx`
- `frontend/src/components/editor/DeckEditor.tsx`
- `progress/2026-04-09-cubos-new-labware.md`

## Verification
- `python -m pip install --force-reinstall "cubos @ git+file:///Users/alexchan/Documents/hephaestus/CubOS@staging"`
- copied CubOS labware definition assets into `site-packages/deck/labware/definitions/`
- `python - <<'PY' ... load_deck_from_yaml('/Users/alexchan/Documents/hephaestus/CubOS/configs/deck/panda_deck.yaml') ... PY`
- `pytest tests/test_deck_router.py` -> passed
- `pytest tests/` -> 26 passed
- `cd frontend && npm test -- --run src/components/deck/DeckVisualization.test.tsx src/App.test.tsx` -> passed
- `cd frontend && npm test` -> 8 passed
- `cd frontend && npm run build` -> passed

## Next Steps
- Upstream CubOS should package `deck/labware/definitions/registry.yaml` and the definition folders in its wheel so the local site-packages copy hack is no longer needed.
