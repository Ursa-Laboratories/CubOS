## Status

complete

## Goal

Fix the Deck tab import flow so selecting a deck config loads it into the working deck file `panda-deck.yaml` instead of dropping back to an empty editor.

## Findings

- The current deck import UI only switches the selected filename.
- The deck editor keeps local labware state, so it needs to resync when a loaded deck changes.
- The requested behavior is to copy the imported deck config into `panda-deck.yaml` and continue editing that file.

## Files Touched

- `frontend/src/App.tsx`
- `frontend/src/components/editor/DeckEditor.tsx`
- `frontend/src/App.test.tsx`

## Verification

- Passed: `cd frontend && npm test -- --run src/App.test.tsx`
- Build still fails in pre-existing deck visualization typing/tests unrelated to this import change:
  - `src/components/deck/DeckVisualization.test.tsx`
  - `src/components/deck/HolderRenderer.tsx`
  - `src/components/deck/TipRackRenderer.tsx`

## Risks / Next Steps

- Assumes imported deck YAML is valid through the existing deck GET/PUT APIs.
- Full `npm run build` remains blocked by unrelated TypeScript issues in the deck visualization code.
