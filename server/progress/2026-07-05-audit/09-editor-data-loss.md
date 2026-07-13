# Editor data-loss guards — dirty checks, save errors, discard, key collisions

**Context:** `frontend/src/App.tsx`, `frontend/src/components/editor/{DeckEditor,GantryEditor,ProtocolEditor}.tsx`, `ImportFromFile.tsx`. Tests: `cd frontend && npm run test`; `App.test.tsx` has a stateful fetch mock to extend.

## 1. CRITICAL — switching files silently discards unsaved edits (`App.tsx:155-167`, `ImportFromFile.tsx:14-28`)

File-picker changes clear `localDeck`/`localGantry`/`localProtocolSteps`/`localProtocolPositions` with no dirty check. Worse, `handleImportDeck` (`App.tsx:220-237`) overwrites `configs/deck/panda-deck.yaml` on disk with the imported file's content, clobbering a shipped config without warning.

**Fix:** wrap the three file setters in guard functions: if the corresponding dirty flag (`deckDirty`/`gantryDirty`/`protocolDirty`, `App.tsx:199-201`) is set, `window.confirm("Discard unsaved <deck|gantry|protocol> changes?")` and abort on cancel. Apply the same guard before `handleImportDeck` writes, and make the import confirm mention it will overwrite `panda-deck.yaml`. Tests: dirty deck + select other file + cancel → edits retained; confirm → switched.

## 2. MAJOR — no `beforeunload` guard for unsaved edits

**Fix:** in `App.tsx`, effect keyed on `unsavedConfigs.length`: register `beforeunload` handler (`preventDefault` + `returnValue = ""`) when > 0, remove on cleanup.

## 3. MAJOR — failed saves are invisible (`DeckEditor.tsx:139-140`, `GantryEditor.tsx:212-213`, `ProtocolEditor.tsx:252-253`)

Save errors go to `console.error`; the user sees a stuck dirty banner and a blocked Run with no reason.

**Fix:** in each editor add `saveError` state; set from the catch (`err.message`), clear on next successful save or edit; render as a red banner near the Save button (reuse the `importErrorStyle` pattern from `App.tsx:537-545`). Tests: PUT returns 400 → banner shows the message; next successful save clears it.

## 4. MAJOR — no way to discard edits to the current file (`onRefresh` prop is dead)

`refreshAll` is passed as `onRefresh` to all three editors but never used; re-selecting the same filename is a React state bailout no-op.

**Fix:** in each editor, when dirty, render a "Discard changes" button next to Save that confirms then calls `onRefresh()` and clears local state. Ensure the reset effects in `App.tsx` actually reset local copies when the query refetch returns (they key on filename — also key them on the refetched data identity, or have the discard handler clear the local state directly).

## 5. MAJOR — `addLabware` key collision destroys a configured plate (`DeckEditor.tsx:116-124`)

Key derived from `Object.keys(labware).length + 1`: add two plates, remove the first, add another → new key collides with `wellplate_2` and replaces it with a blank template (calibration lost). `GantryEditor.addInstrument` (`GantryEditor.tsx:140-145`) already has the correct `while (exists) idx++` loop.

**Fix:** copy the GantryEditor uniqueness loop. Test: add/remove/add sequence → three distinct keys ever used, no overwrite.

## 6. MINOR — emptying a protocol/deck hides the Save bar (`ProtocolEditor.tsx:458`, `DeckEditor.tsx:180`)

`hasSteps &&` / `hasItems &&` gate the whole action bar — deleting the last item strands a dirty editor with no Save/Discard. **Fix:** always render the action bar; when empty, disable Save with hint text ("Add at least one step/labware"), keep Discard available.

**Done when:** all items implemented with tests, full frontend suite + lint green.
