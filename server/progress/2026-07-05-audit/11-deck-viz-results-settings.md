# Deck visualization, Results tab, settings — correctness and empty states

**Context:** `frontend/src/App.tsx`, `frontend/src/components/deck/*`, `frontend/src/components/data/DataOutputPanel.tsx`, `frontend/src/api/client.ts`, `zoo/routers/data.py`. Tests: `cd frontend && npm run test`, backend `.venv/bin/python -m pytest tests/ -q`.

## 1. MAJOR — live well preview never applies to already-loaded plates (`App.tsx:177`, `DeckEditor.tsx:64`)

`displayDeck` prefers `item.wells` (stale server copy) over `previewWells`, so editing calibration/rows/pitch of an existing plate shows old well positions until save; the `/deck/preview-wells` round trip is computed then discarded. **Fix:** when `localDeck` is non-null, prefer the preview: `wells: previewWells[item.key] ?? item.wells ?? null`. Test: edit A1 calibration of a loaded plate → visualization wells move before saving.

## 2. MAJOR — ASMI export unreachable from UI (`api/client.ts:239-244`, `DataOutputPanel.tsx:90-102`)

Backend `GET /api/data/campaigns/{id}/asmi.zip` exists and is documented; UI only exposes `measurements.zip`; `asmi_measurement_count` is fetched and unused. **Fix:** add `exportCampaignAsmiZip` to `dataApi` (`download(...)`); render a second "ASMI ZIP" button per row, enabled when `asmi_measurement_count > 0`.

## 3. MINOR — first-run Results tab shows a raw 404 error (`data.py:94-103`, `DataOutputPanel.tsx:54-56`)

Before any run, the DB file is absent → `Data load failed: 404: {"detail":...}`. **Fix (backend, preferred):** in `list_campaigns`, catch `DataDatabaseNotFoundError` and return `[]` (keep 404s for the zip exports). Frontend: render `campaigns=[]` as "No campaigns yet — run a protocol to create one." Update the existing missing-DB test to expect `[]`.

## 4. MINOR — "Run time" column renders a raw ISO timestamp (`DataOutputPanel.tsx:86`)

**Fix:** rename header to "Last measured", format via `new Date(v).toLocaleString()` with raw-string fallback.

## 5. MINOR — mm-vs-px distortion in deck visualization (`VialRenderer.tsx:29`, `WellPlateRenderer.tsx:21`, `DeckVisualization.tsx:27-28`)

Vial radius uses mm as px; wells fixed 3px; X/Y scales differ on the fixed 600×420 canvas. **Fix:** compute `pxPerMmX`/`pxPerMmY` from ranges; scale radii by `Math.min(pxPerMmX, pxPerMmY)`; letterbox so both axes share one scale (keep existing Y inversion in `utils/coordinates.ts` — it is correct). Update `DeckVisualization.test.tsx` accordingly.

## 6. MINOR — changing config dir keeps stale file selections (`App.tsx:70-86,208-218`)

After Browse→new dir, `deckFile`/`gantryFile`/`protocolFile` still point at old-dir names → three 404 banners. **Fix:** on config-dir change, also null out the three file selections (dirty-guard via the file-switch confirm from file 09 if edits exist).

## 7. MINOR — API errors surface raw JSON app-wide (`api/client.ts:12-16`)

Every banner shows `500: {"detail":"..."}`. **Fix:** in `request()` and `download()`, try `JSON.parse(text)`; if `detail` is a string use it as the message, else keep raw text. Keep the status code prefix out of the user-facing message (banners already say what failed). Update tests that assert on the old format.

## 8. MINOR — holder/tip-rack note (`DeckEditor.tsx:172-176`)

Preview only covers top-level well plates; append "the visualization updates after saving" to the unsupported-labware note.

**Done when:** all items implemented, affected tests updated, full frontend + backend suites and lint green.
