# UI redesign — design system + app shell

## Status

complete

## Goal

Re-envision the Zoo frontend as a modern, calm, scientist-friendly UI: one
coherent visual system instead of ad-hoc inline grays, with a proper app
shell and instrument-panel styling for readouts.

## What changed (styling only — no behavior, routes, or CubOS boundary changes)

- **New `frontend/src/theme.ts`** — single source of truth for the visual
  language: slate neutral scale, one indigo accent (#4f46e5), semantic
  danger/warning/success tints, radii, shadows, font stacks, and shared
  style objects (`card`, `input`, `btn.primary/secondary/ghost/danger`,
  `notice.*`, `sectionLabel`, `panelTitle`, `pill`, `mono`). Components keep
  the repo's inline-style convention but pull every color/radius/shadow from
  here. `theme.color.danger` stays `#dc2626` — fields.test.tsx pins it.
- **`index.css`** — foundation only: base typography (tabular numerals
  globally), uniform button hover/active + disabled states, accent focus
  rings, slim slate scrollbars, reduced-motion support. Interaction states
  live here because inline styles can't express them.
- **App shell** (`AppLayout.tsx`, `App.tsx`) — new header bar (brand mark,
  Workflow/Results segmented switcher, run-status pill with Cancel, Last
  Campaign, Config Directory + Browse) over a card-based two-column
  workspace on a soft slate canvas. `AppLayout` gained a `header` prop.
- **All major surfaces restyled to tokens**: EditorTabs (accent underline,
  mono filename line), fields.tsx, ImportFromFile, DeckEditor, GantryEditor,
  ProtocolEditor (step cards with neutral mono step badges; Run is the sole
  primary action), GantryPositionWidget (sunken instrument-style position
  readout, 26px tabular-nums digits), CalibrationWizard (overlay dialog
  chrome, accent/success step rail), DataOutputPanel (uppercase micro table
  headers, mono numeric cells).
- **Deck visualization SVG** — slate schematic palette, indigo gantry
  crosshair with halo, and white text halos (`paintOrder="stroke"`) on all
  labware labels so dense vial rows stay legible. Geometry untouched.

## Verification

- `cd frontend && npm run lint` — clean.
- `cd frontend && npx vitest run` — 16 files, 174/174 passed.
- `cd frontend && npm run build` — clean.
- Visual: launched `python -m zoo` with sample CubOS configs copied into
  `configs/`, drove Gantry/Deck/Protocol/Results via Playwright, inspected
  screenshots of every surface.

## Risks / Next Steps

- Purely cosmetic diff; behavior, accessibility names, and test surface
  unchanged. If a colorway tweak is wanted (e.g. different accent), edit
  `frontend/src/theme.ts` only.
- `configs/` now contains sample YAMLs copied from CubOS for the visual
  check; delete if unwanted (directory is local working data, untracked).
